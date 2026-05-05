"""Unit tests for `docgen demo-function`.

Most tests here are pure-data: they exercise manifest loading, validation,
action rendering, fragment/cache-key stability, and CLI exit-code mapping
without launching Playwright or ffmpeg. The few tests that need actual
rendering are guarded with `pytest.importorskip` / `shutil.which` checks so
the suite passes on CI runners without Playwright or ffmpeg installed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from docgen import demo_function as df
from docgen.demo_function import (
    Action,
    ManifestError,
    PlaceholderManifest,
    SUPPORTED_ACTION_KINDS,
    _coerce,
    _render_action,
    generate_capture_script,
    load_manifest,
    run_cli,
)


# ---------------------------------------------------------------------------
# Manifest loading — YAML sidecar (shape #1)
# ---------------------------------------------------------------------------


def _yaml_manifest_text(**overrides: object) -> str:
    base = {
        "identifier": "repo/path.ts:fn",
        "intent": "Does the thing.",
        "demonstration": {
            "kind": "playwright",
            "url": "http://127.0.0.1:3000/x",
            "actions": [
                {"kind": "click", "selector": "[data-testid=\"go\"]"},
            ],
        },
        "output_budget": {"duration_seconds": 10, "resolution": "1280x720"},
    }
    base.update(overrides)
    import yaml as _y
    return _y.safe_dump(base)


def test_load_yaml_sidecar_minimal(tmp_path: Path) -> None:
    p = tmp_path / "m.docgen.yaml"
    p.write_text(_yaml_manifest_text(), encoding="utf-8")
    m = load_manifest(p)
    assert m.identifier == "repo/path.ts:fn"
    assert m.intent == "Does the thing."
    assert m.kind == "playwright"
    assert m.url == "http://127.0.0.1:3000/x"
    assert [a.kind for a in m.actions] == ["click"]
    assert m.resolution == "1280x720"


def test_load_yaml_string_path(tmp_path: Path) -> None:
    p = tmp_path / "m.docgen.yaml"
    p.write_text(_yaml_manifest_text(), encoding="utf-8")
    m = load_manifest(str(p))
    assert m.identifier == "repo/path.ts:fn"


# ---------------------------------------------------------------------------
# Manifest loading — Python @pytest.mark.docgen marker (shape #2)
# ---------------------------------------------------------------------------


_SAMPLE_PY = '''
"""Module docstring that mentions @pytest.mark.docgen — should NOT match.

A naive regex over this file would pick up text inside this docstring
and confuse it for a real marker; the AST-based loader must ignore it.
"""
import pytest


@pytest.mark.docgen(
    identifier="repo/path.ts:fn",
    intent="Does the thing.",
    demonstration={
        "kind": "playwright",
        "url": "http://127.0.0.1:3000/x",
        "actions": [
            {"kind": "type", "selector": "#title", "value": "hi", "delay_ms": 30},
            {"kind": "click", "selector": "#go"},
        ],
    },
    output_budget={"duration_seconds": 10, "resolution": "1280x720"},
    assertions_to_surface=["x.y === 1"],
)
def test_thing():
    pass
'''


def test_python_marker_basic(tmp_path: Path) -> None:
    p = tmp_path / "sample_test.py"
    p.write_text(_SAMPLE_PY, encoding="utf-8")
    m = load_manifest(f"{p}::test_thing")
    assert m.identifier == "repo/path.ts:fn"
    assert m.intent == "Does the thing."
    assert [a.kind for a in m.actions] == ["type", "click"]
    assert m.assertions_to_surface == ["x.y === 1"]


def test_python_marker_ignores_docstring_text(tmp_path: Path) -> None:
    """F7 regression: regex-over-source readers match docstring text.

    `_load_pytest_marker` uses `ast.walk` over the parsed module — a
    docstring that *talks about* the marker must not be parsed as one.
    The marker is on `test_thing`; a function without one must error.
    """
    src = '''
"""This file mentions pytest.mark.docgen(identifier=\\"X\\", intent=\\"Y\\") in prose."""

def test_no_marker():
    pass
'''
    p = tmp_path / "no_marker.py"
    p.write_text(src, encoding="utf-8")
    with pytest.raises(ManifestError, match="missing @pytest.mark.docgen"):
        load_manifest(f"{p}::test_no_marker")


def test_python_marker_unknown_function(tmp_path: Path) -> None:
    p = tmp_path / "sample_test.py"
    p.write_text(_SAMPLE_PY, encoding="utf-8")
    with pytest.raises(ManifestError, match="function not found"):
        load_manifest(f"{p}::missing_fn")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_missing_identifier(tmp_path: Path) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(_yaml_manifest_text(identifier=""), encoding="utf-8")
    with pytest.raises(ManifestError, match="missing required field: 'identifier'"):
        load_manifest(p)


def test_invalid_kind() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "selenium"},
    }
    with pytest.raises(ManifestError, match="must be 'playwright' or 'cli'"):
        _coerce(raw)


def test_cli_kind_requires_tape() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "cli"},
    }
    with pytest.raises(ManifestError, match="demonstration.tape is required"):
        _coerce(raw)


def test_playwright_spec_requires_grep(tmp_path: Path) -> None:
    spec = tmp_path / "t.spec.ts"
    spec.write_text("//", encoding="utf-8")
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "spec": str(spec)},
    }
    with pytest.raises(ManifestError, match="demonstration.grep is required"):
        _coerce(raw, source_path=tmp_path / "m.docgen.yaml")


def test_playwright_spec_xor_url(tmp_path: Path) -> None:
    spec = tmp_path / "t.spec.ts"
    spec.write_text("//", encoding="utf-8")
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {
            "kind": "playwright",
            "spec": str(spec),
            "grep": "my test",
            "url": "http://x",
        },
    }
    with pytest.raises(ManifestError, match="either demonstration.spec"):
        _coerce(raw, source_path=tmp_path / "m.docgen.yaml")


def test_duration_hard_cap() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
        "output_budget": {"duration_seconds": 120, "resolution": "1280x720"},
    }
    with pytest.raises(ManifestError, match="exceeds the 60s hard cap"):
        _coerce(raw)


def test_invalid_resolution() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
        "output_budget": {"duration_seconds": 10, "resolution": "1280-720"},
    }
    with pytest.raises(ManifestError, match="output_budget.resolution must match"):
        _coerce(raw)


def test_unknown_action_kind() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {
            "kind": "playwright",
            "url": "http://x",
            "actions": [{"kind": "teleport"}],
        },
    }
    with pytest.raises(ManifestError, match="unsupported action kind: 'teleport'"):
        _coerce(raw)


def test_assertions_length_cap() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
        "assertions_to_surface": ["x" * 61],
    }
    with pytest.raises(ManifestError, match="≤ 60 chars"):
        _coerce(raw)


# ---------------------------------------------------------------------------
# Action -> Playwright source line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,expected_substring",
    [
        (Action("goto", {"url": "http://x"}), 'page.goto(\'http://x\''),
        (Action("click", {"selector": "[data-testid=\"x\"]"}), "page.click(\'[data-testid=\"x\"]\'"),
        (Action("fill", {"selector": "#a", "value": "v"}), "page.fill('#a', 'v')"),
        (Action("type", {"selector": "#a", "value": "v"}), "page.keyboard.type('v', delay=40)"),
        (Action("wait_for", {"selector": "#a"}), "page.wait_for_selector('#a', timeout=10000)"),
        (
            Action("wait_for_text", {"selector": "[data-testid=\"x\"]", "text": "ok"}),
            ".filter(has_text=\'ok\').first.wait_for(state=\"visible\"",
        ),
        (Action("wait", {"ms": 250}), "page.wait_for_timeout(250)"),
        (Action("screenshot", {"path": "/tmp/x.png"}), "page.screenshot(path='/tmp/x.png')"),
    ],
)
def test_render_action(action: Action, expected_substring: str) -> None:
    line = _render_action(action)
    assert expected_substring in line


def test_supported_action_kinds_set() -> None:
    """The spec lists exactly these eight kinds — guard against accidental drift."""
    assert set(SUPPORTED_ACTION_KINDS) == {
        "goto", "click", "fill", "type", "wait_for",
        "wait_for_text", "wait", "screenshot",
    }


def test_generated_script_compiles(tmp_path: Path) -> None:
    """The generated capture script must be valid Python (compileable)."""
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {
            "kind": "playwright",
            "url": "http://127.0.0.1/x",
            "actions": [
                {"kind": "type", "selector": "#a", "value": "v", "delay_ms": 30},
                {"kind": "click", "selector": "[data-testid=\"go\"]"},
                {"kind": "wait_for_text", "selector": "#status", "text": "ok"},
                {"kind": "wait", "ms": 100},
            ],
        },
        "output_budget": {"duration_seconds": 10, "resolution": "640x480"},
    }
    m = _coerce(raw)
    script = generate_capture_script(m, output_path=tmp_path / "out.mp4")
    compile(script, "<generated>", "exec")
    assert "record_video_size" in script
    assert "viewport=" in script
    assert "640" in script and "480" in script


# ---------------------------------------------------------------------------
# fragment_id and cache_key stability
# ---------------------------------------------------------------------------


def test_fragment_id_format() -> None:
    raw = {
        "identifier": "courseforge/Course Builder/src/Foo.ts:compileLesson!",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
    }
    m = _coerce(raw)
    assert m.fragment_id == "fn-courseforge-course-builder-src-foo-ts-compilelesson"
    import re as _re
    assert _re.match(r"^fn-[a-z0-9-]+$", m.fragment_id)


def test_cache_key_stable_and_changes_with_input(tmp_path: Path) -> None:
    """Cache key = sha256(fn_source_sha + intent_sha + fixture_sha) (issue #47)."""
    src = tmp_path / "source.txt"
    src.write_text("fn", encoding="utf-8")
    raw1 = {
        "identifier": "x:y",
        "intent": "first",
        "demonstration": {"kind": "playwright", "url": "http://x"},
    }
    m1a = _coerce(raw1, source_path=src)
    m1b = _coerce(raw1, source_path=src)
    raw2 = dict(raw1, intent="second")
    m2 = _coerce(raw2, source_path=src)
    assert m1a.cache_key == m1b.cache_key
    assert m1a.cache_key != m2.cache_key
    assert len(m1a.cache_key) == 16


def test_cache_key_includes_fixture_contents(tmp_path: Path) -> None:
    fixture = tmp_path / "fix.txt"
    fixture.write_text("alpha", encoding="utf-8")

    src = tmp_path / "m.yaml"
    src.write_text(
        _yaml_manifest_text(setup={"fixtures": ["fix.txt"]}),
        encoding="utf-8",
    )
    m1 = load_manifest(src)
    k1 = m1.cache_key

    fixture.write_text("beta", encoding="utf-8")
    m2 = load_manifest(src)
    k2 = m2.cache_key
    assert k1 != k2


# ---------------------------------------------------------------------------
# Placeholder skip + tooling-missing exit code mapping
# ---------------------------------------------------------------------------


def test_render_raises_placeholder(tmp_path: Path) -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright"},
    }
    m = _coerce(raw)
    with pytest.raises(PlaceholderManifest):
        df.render(m, tmp_path / "out", no_narration=True)


def test_run_cli_neutral_skip(tmp_path: Path, capsys) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(
        _yaml_manifest_text(
            demonstration={"kind": "playwright", "actions": []},
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    code = run_cli(str(p), str(out_dir), no_narration=True)
    assert code == df.EXIT_NEUTRAL_SKIP
    err = capsys.readouterr().err
    assert "neutral skip" in err
    # Acceptance #9: writes nothing to output-dir.
    assert not list(out_dir.iterdir()) if out_dir.exists() else True


def test_run_cli_invalid_manifest_duration(tmp_path: Path, capsys) -> None:
    p = tmp_path / "m.yaml"
    p.write_text(
        _yaml_manifest_text(
            output_budget={"duration_seconds": 120, "resolution": "1280x720"},
        ),
        encoding="utf-8",
    )
    code = run_cli(str(p), str(tmp_path / "out"), no_narration=True)
    assert code == df.EXIT_INVALID
    assert "exceeds the 60s hard cap" in capsys.readouterr().err


def test_run_cli_missing_manifest_file(tmp_path: Path, capsys) -> None:
    code = run_cli(str(tmp_path / "no.yaml"), str(tmp_path / "out"), no_narration=True)
    assert code == df.EXIT_INVALID


# ---------------------------------------------------------------------------
# End-to-end render (cli kind, ffmpeg-only — no Playwright required)
# ---------------------------------------------------------------------------


def _ffmpeg_present() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _vhs_present() -> bool:
    return shutil.which("vhs") is not None


@pytest.mark.skipif(
    not _ffmpeg_present() or not _vhs_present(),
    reason="ffmpeg / ffprobe / vhs not installed",
)
def test_render_cli_kind_emits_artifacts(tmp_path: Path, monkeypatch) -> None:
    """End-to-end render using kind=cli (VHS tape → MP4).

    Covers assertion burn-in, caching, and artifact layout (no narration).
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        'Set Shell "bash --norc --noprofile"\n'
        "Set Width 320\n"
        "Set Height 240\n"
        "Sleep 300ms\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "m.docgen.yaml"
    manifest_path.write_text(
        _yaml_manifest_text(
            demonstration={
                "kind": "cli",
                "tape": "demo.tape",
            },
        ),
        encoding="utf-8",
    )
    m = load_manifest(manifest_path)

    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    result = df.render(m, out_dir, cache_dir=cache_dir, no_narration=True)
    assert result.cache_status == "miss"

    for name in ("rendered.mp4", "poster.png", "fragment.txt", "manifest.json", "cache-status.txt"):
        assert (out_dir / name).exists(), f"missing artifact: {name}"

    fragment_text = (out_dir / "fragment.txt").read_text(encoding="utf-8")
    assert fragment_text == m.fragment_id
    assert not fragment_text.endswith("\n")

    snapshot = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    expected_keys = {
        "identifier", "intent", "fragment_id", "cache_key",
        "duration_seconds", "resolution", "assertions_to_surface", "narration",
    }
    assert expected_keys.issubset(snapshot.keys())
    assert snapshot["narration"] is None

    assert (out_dir / "cache-status.txt").read_text() == "miss\n"

    head = (out_dir / "rendered.mp4").read_bytes()[:12]
    assert b"ftyp" in head, "rendered.mp4 should be a real ISO MP4"

    out2 = tmp_path / "out2"
    result2 = df.render(m, out2, cache_dir=cache_dir, no_narration=True)
    assert result2.cache_status == "hit"
    assert (out2 / "cache-status.txt").read_text() == "hit\n"
    for name in ("rendered.mp4", "poster.png", "fragment.txt", "manifest.json"):
        assert (out2 / name).exists()


@pytest.mark.skipif(
    not _ffmpeg_present() or not _vhs_present(),
    reason="ffmpeg / ffprobe / vhs not installed",
)
def test_render_warns_when_openai_key_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    """No OPENAI_API_KEY → warning + visual-only video."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        'Set Shell "bash --norc --noprofile"\n'
        "Set Width 320\n"
        "Set Height 240\n"
        "Sleep 300ms\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "m.docgen.yaml"
    manifest_path.write_text(
        _yaml_manifest_text(
            demonstration={
                "kind": "cli",
                "tape": "demo.tape",
            },
            output_budget={"duration_seconds": 1, "resolution": "320x240"},
        ),
        encoding="utf-8",
    )
    m = load_manifest(manifest_path)
    df.render(m, tmp_path / "out", no_narration=False)
    err = capsys.readouterr().err
    assert "OPENAI_API_KEY not set" in err


# ---------------------------------------------------------------------------
# Equivalence between YAML and Python marker shapes (acceptance #8)
# ---------------------------------------------------------------------------


def test_yaml_and_python_marker_produce_equivalent_manifests(tmp_path: Path) -> None:
    yaml_path = tmp_path / "m.docgen.yaml"
    yaml_path.write_text(_yaml_manifest_text(), encoding="utf-8")
    py_path = tmp_path / "sample_test.py"
    py_path.write_text(_SAMPLE_PY, encoding="utf-8")

    a = load_manifest(yaml_path)

    b_src = '''
import pytest

@pytest.mark.docgen(
    identifier="repo/path.ts:fn",
    intent="Does the thing.",
    demonstration={
        "kind": "playwright",
        "url": "http://127.0.0.1:3000/x",
        "actions": [{"kind": "click", "selector": '[data-testid="go"]'}],
    },
    output_budget={"duration_seconds": 10, "resolution": "1280x720"},
)
def test_thing():
    pass
'''
    b_path = tmp_path / "equiv_test.py"
    b_path.write_text(b_src, encoding="utf-8")
    b = load_manifest(f"{b_path}::test_thing")

    assert a.identifier == b.identifier
    assert a.intent == b.intent
    assert a.kind == b.kind
    assert a.url == b.url
    assert [act.kind for act in a.actions] == [act.kind for act in b.actions]
    assert a.resolution == b.resolution
    assert a.duration_seconds == b.duration_seconds
