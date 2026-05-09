"""Unit tests for `docgen demo-function`.

Most tests here are pure-data: they exercise manifest loading, validation,
action rendering, fragment/cache-key stability, and CLI exit-code mapping
without launching Playwright or ffmpeg. VHS+ffmpeg render tests rely on
``tests/conftest.py`` + ``tests/_render_tools_bootstrap.py`` to put tooling on
PATH (see repo ``tests/.bin-cache/``). Playwright e2e tests use the same hook
for browser binaries.
"""

from __future__ import annotations

import json
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
    manifest_from_mapping,
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


def test_manifest_from_mapping_cli(tmp_path: Path) -> None:
    """Programmatic manifest for VHS (no Playwright test files)."""
    tape = tmp_path / "demo.tape"
    tape.write_text("Output out.mp4\n", encoding="utf-8")
    sidecar = tmp_path / "side.docgen.yaml"
    raw = {
        "identifier": "cli:demo",
        "intent": "Shows the CLI.",
        "demonstration": {"kind": "cli", "tape": "demo.tape"},
        "output_budget": {"duration_seconds": 15, "resolution": "1280x720"},
    }
    m = manifest_from_mapping(raw, source_path=sidecar)
    assert m.kind == "cli"
    assert m.cli_tape == tape.resolve()


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


def test_render_cli_kind_emits_artifacts(tmp_path: Path, monkeypatch) -> None:
    """End-to-end render using kind=cli (VHS tape → MP4).

    Covers assertion burn-in, caching, and artifact layout (no narration).
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        "Set Shell bash\n"
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


def test_render_fails_when_openai_key_missing(tmp_path: Path, monkeypatch) -> None:
    """No ``OPENAI_API_KEY`` and no ``--no-narration`` → hard fail.

    Refuses to emit a silent demo masquerading as a complete artifact;
    callers must explicitly opt in via ``no_narration=True``.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        "Set Shell bash\n"
        "Set Width 320\n"
        "Set Height 240\n"
        "Sleep 300ms\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "m.docgen.yaml"
    manifest_path.write_text(
        _yaml_manifest_text(
            demonstration={"kind": "cli", "tape": "demo.tape"},
            output_budget={"duration_seconds": 1, "resolution": "320x240"},
        ),
        encoding="utf-8",
    )
    m = load_manifest(manifest_path)
    with pytest.raises(df.ToolingMissingError, match=r"OPENAI_API_KEY"):
        df.render(m, tmp_path / "out", no_narration=False)


def test_render_no_narration_opt_in_emits_silent_clip(tmp_path: Path, monkeypatch) -> None:
    """``no_narration=True`` is the explicit silent-clip opt-in (no key needed)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        "Set Shell bash\n"
        "Set Width 320\n"
        "Set Height 240\n"
        "Sleep 300ms\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "m.docgen.yaml"
    manifest_path.write_text(
        _yaml_manifest_text(
            demonstration={"kind": "cli", "tape": "demo.tape"},
            output_budget={"duration_seconds": 1, "resolution": "320x240"},
        ),
        encoding="utf-8",
    )
    m = load_manifest(manifest_path)
    out_dir = tmp_path / "out"
    df.render(m, out_dir, no_narration=True)
    assert (out_dir / "rendered.mp4").exists()
    snapshot = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert snapshot["narration"] is None


def test_run_cli_returns_tooling_missing_when_no_key(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI surfaces missing ``OPENAI_API_KEY`` as ``EXIT_TOOLING_MISSING``."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        "Set Shell bash\n"
        "Set Width 320\n"
        "Set Height 240\n"
        "Sleep 200ms\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "m.docgen.yaml"
    manifest_path.write_text(
        _yaml_manifest_text(
            demonstration={"kind": "cli", "tape": "demo.tape"},
            output_budget={"duration_seconds": 1, "resolution": "320x240"},
        ),
        encoding="utf-8",
    )
    code = run_cli(str(manifest_path), str(tmp_path / "out"), no_narration=False)
    assert code == df.EXIT_TOOLING_MISSING
    err = capsys.readouterr().err
    assert "OPENAI_API_KEY" in err


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


# ---------------------------------------------------------------------------
# Playwright TypeScript: sidecar + inline docgen annotation
# ---------------------------------------------------------------------------


def test_ts_sidecar_loads_and_sets_spec_grep(tmp_path: Path) -> None:
    spec = tmp_path / "lesson.spec.ts"
    spec.write_text("// placeholder\n", encoding="utf-8")
    side = tmp_path / "lesson.docgen.yaml"
    side.write_text(
        _yaml_manifest_text(
            demonstration={
                "kind": "playwright",
                "grep": "compiles",
            },
        ),
        encoding="utf-8",
    )
    m = load_manifest(spec)
    assert m.pw_spec == spec.resolve()
    assert m.pw_grep == "compiles"
    assert m.fn_source_path == spec.resolve()


def test_ts_sidecar_alternate_name_lesson_docgen_yaml(tmp_path: Path) -> None:
    """``lesson.spec.ts`` may pair with ``lesson.docgen.yaml`` (not only ``lesson.spec.docgen.yaml``)."""
    spec = tmp_path / "lesson.spec.ts"
    spec.write_text("//\n", encoding="utf-8")
    alt = tmp_path / "lesson.docgen.yaml"
    alt.write_text(
        _yaml_manifest_text(
            demonstration={
                "kind": "playwright",
                "grep": "g",
            },
        ),
        encoding="utf-8",
    )
    m = load_manifest(spec)
    assert m.pw_grep == "g"


def test_ts_sidecar_requires_grep(tmp_path: Path) -> None:
    spec = tmp_path / "x.spec.ts"
    spec.write_text("//\n", encoding="utf-8")
    side = tmp_path / "x.docgen.yaml"
    side.write_text(
        _yaml_manifest_text(
            demonstration={"kind": "playwright", "url": "http://127.0.0.1/"},
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match=r"demonstration\.grep is required"):
        load_manifest(spec)


def test_ts_inline_json_stringify_contract(tmp_path: Path) -> None:
    spec = tmp_path / "api.spec.ts"
    spec.write_text(
        r'''
import { test, expect } from "@playwright/test";

test("does the thing", async ({ page }) => {
  test.info().annotations.push({
    type: "docgen",
    description: JSON.stringify({
      "identifier": "pkg/Foo.ts:bar",
      "intent": "Runs the demo.",
      "demonstration": {
        "kind": "playwright",
        "url": "http://127.0.0.1:3000/",
        "actions": [{ "kind": "click", "selector": "#go" }],
      },
      "output_budget": { "duration_seconds": 10, "resolution": "800x600" },
    }),
  });
  await page.goto("http://127.0.0.1:3000/");
});
''',
        encoding="utf-8",
    )
    m = load_manifest(spec)
    assert m.identifier == "pkg/Foo.ts:bar"
    assert m.intent == "Runs the demo."
    assert m.url == "http://127.0.0.1:3000/"
    assert m.pw_spec is None
    assert m.pw_grep is None
    assert m.fn_source_path == spec.resolve()
    assert m.resolution == "800x600"


def test_ts_path_with_title_same_as_grep(tmp_path: Path) -> None:
    spec = tmp_path / "api.spec.ts"
    spec.write_text(
        r'''
import { test } from "@playwright/test";

test("Alpha case", async () => {
  test.info().annotations.push({
    type: "docgen",
    description: JSON.stringify({
      "identifier": "a:b",
      "intent": "i",
      "demonstration": { "kind": "playwright", "url": "http://x/", "actions": [] },
    }),
  });
});

test("Beta", async () => {
  test.info().annotations.push({
    type: "docgen",
    description: JSON.stringify({
      "identifier": "c:d",
      "intent": "j",
      "demonstration": { "kind": "playwright", "url": "http://y/", "actions": [] },
    }),
  });
});
''',
        encoding="utf-8",
    )
    m = load_manifest(f"{spec}::Alpha case")
    assert m.identifier == "a:b"
    m2 = load_manifest(spec, grep="Alpha case")
    assert m2.identifier == "a:b"


def test_ts_multiple_docgen_requires_grep(tmp_path: Path) -> None:
    spec = tmp_path / "multi.spec.ts"
    spec.write_text(
        r'''
import { test } from "@playwright/test";

test("one", async () => {
  test.info().annotations.push({
    type: "docgen",
    description: JSON.stringify({
      "identifier": "a:b",
      "intent": "i",
      "demonstration": { "kind": "playwright", "url": "http://x/", "actions": [] },
    }),
  });
});

test("two", async () => {
  test.info().annotations.push({
    type: "docgen",
    description: JSON.stringify({
      "identifier": "c:d",
      "intent": "j",
      "demonstration": { "kind": "playwright", "url": "http://y/", "actions": [] },
    }),
  });
});
''',
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="multiple docgen"):
        load_manifest(spec)


def test_run_cli_passes_grep_to_ts_manifest(tmp_path: Path) -> None:
    spec = tmp_path / "z.spec.ts"
    spec.write_text("//\n", encoding="utf-8")
    from unittest.mock import patch

    with patch.object(df, "load_manifest") as lm:
        lm.side_effect = ManifestError("stop early")
        code = run_cli(str(spec), str(tmp_path / "out"), grep="pick me", no_narration=True)
    assert code == df.EXIT_INVALID
    lm.assert_called_once_with(str(spec), grep="pick me")


# ---------------------------------------------------------------------------
# playback_speed_factor: parsing, validation, cache key
# ---------------------------------------------------------------------------


def test_playback_speed_factor_default_is_one() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
    }
    m = _coerce(raw)
    assert m.playback_speed_factor == df.DEFAULT_PLAYBACK_SPEED_FACTOR == 1.0


def test_playback_speed_factor_parses_float() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
        "output_budget": {"playback_speed_factor": 0.5},
    }
    m = _coerce(raw)
    assert m.playback_speed_factor == 0.5


def test_playback_speed_factor_rejects_out_of_range() -> None:
    base = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
    }
    too_low = dict(base, output_budget={"playback_speed_factor": 0.0})
    with pytest.raises(ManifestError, match="playback_speed_factor"):
        _coerce(too_low)
    too_high = dict(
        base,
        output_budget={"playback_speed_factor": df.MAX_PLAYBACK_SPEED_FACTOR + 1},
    )
    with pytest.raises(ManifestError, match="playback_speed_factor"):
        _coerce(too_high)


def test_playback_speed_factor_rejects_non_numeric() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
        "output_budget": {"playback_speed_factor": "slow"},
    }
    with pytest.raises(ManifestError, match="must be a number"):
        _coerce(raw)


def test_cache_key_changes_with_playback_speed_factor(tmp_path: Path) -> None:
    src = tmp_path / "source.txt"
    src.write_text("fn", encoding="utf-8")
    base = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {"kind": "playwright", "url": "http://x"},
    }
    m1 = _coerce(base, source_path=src)
    m2 = _coerce(
        dict(base, output_budget={"playback_speed_factor": 0.5}),
        source_path=src,
    )
    assert m1.cache_key != m2.cache_key


# ---------------------------------------------------------------------------
# Action.say: parsing, cache invalidation
# ---------------------------------------------------------------------------


def test_action_say_field_parses() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {
            "kind": "playwright",
            "url": "http://x",
            "actions": [
                {"kind": "click", "selector": "#go", "say": "Click the button."},
                {"kind": "wait", "ms": 250},
            ],
        },
    }
    m = _coerce(raw)
    assert m.actions[0].say == "Click the button."
    assert m.actions[1].say is None


def test_action_say_rejects_non_string() -> None:
    raw = {
        "identifier": "x:y",
        "intent": "z",
        "demonstration": {
            "kind": "playwright",
            "url": "http://x",
            "actions": [{"kind": "click", "selector": "#go", "say": 42}],
        },
    }
    with pytest.raises(ManifestError, match="action.say must be a string"):
        _coerce(raw)


def test_cache_key_changes_with_action_say(tmp_path: Path) -> None:
    """When the manifest is the canonical source, adding ``say`` to an action
    must change the cache key (the YAML on disk changes, so its bytes hash
    changes too)."""
    base_yaml = _yaml_manifest_text(
        demonstration={
            "kind": "playwright",
            "url": "http://x",
            "actions": [{"kind": "click", "selector": "#go"}],
        },
    )
    say_yaml = _yaml_manifest_text(
        demonstration={
            "kind": "playwright",
            "url": "http://x",
            "actions": [{"kind": "click", "selector": "#go", "say": "Hi."}],
        },
    )
    p1 = tmp_path / "no_say.docgen.yaml"
    p1.write_text(base_yaml, encoding="utf-8")
    p2 = tmp_path / "with_say.docgen.yaml"
    p2.write_text(say_yaml, encoding="utf-8")

    m_no_say = load_manifest(p1)
    m_say = load_manifest(p2)
    assert m_no_say.cache_key != m_say.cache_key


# ---------------------------------------------------------------------------
# Timeline → WebVTT: scaled cue timestamps
# ---------------------------------------------------------------------------


def test_vtt_from_timeline_scales_with_speed_factor() -> None:
    timeline = [
        {"kind": "click", "say": "First.", "t_start_ms": 1000, "t_end_ms": 1100},
        {"kind": "click", "say": "Second.", "t_start_ms": 3000, "t_end_ms": 3100},
    ]
    full_speed = df._vtt_from_timeline(timeline, speed_factor=1.0, total_sec=10.0)
    assert "00:00:01.000 -->" in full_speed
    assert "00:00:03.000 -->" in full_speed
    assert "First." in full_speed
    assert "Second." in full_speed

    half_speed = df._vtt_from_timeline(timeline, speed_factor=0.5, total_sec=10.0)
    # at 0.5x, t=1s in recording becomes t=2s in playback.
    assert "00:00:02.000 -->" in half_speed
    assert "00:00:06.000 -->" in half_speed


def test_vtt_from_timeline_skips_actions_without_say() -> None:
    timeline = [
        {"kind": "click", "say": None, "t_start_ms": 100, "t_end_ms": 200},
        {"kind": "wait", "say": "spoken", "t_start_ms": 500, "t_end_ms": 600},
    ]
    vtt = df._vtt_from_timeline(timeline, speed_factor=1.0, total_sec=5.0)
    assert "spoken" in vtt
    # Only one cue → numbered "1".
    assert vtt.count("00:00:00.500 -->") == 1


def test_vtt_from_timeline_empty_when_no_say() -> None:
    timeline = [{"kind": "wait", "say": None, "t_start_ms": 100, "t_end_ms": 200}]
    vtt = df._vtt_from_timeline(timeline, speed_factor=1.0, total_sec=5.0)
    assert vtt == "WEBVTT\n\n"


# ---------------------------------------------------------------------------
# _retime_video / _mux_audio_padded: ffmpeg helpers
# ---------------------------------------------------------------------------


def _make_silent_clip(path: Path, *, seconds: float, width: int = 320, height: int = 240) -> None:
    """Generate a deterministic test MP4 (color bars + silence) via ffmpeg."""
    import subprocess

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=blue:s={width}x{height}:d={seconds}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-t", str(seconds),
        "-movflags", "+faststart",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]


def _make_silent_audio(path: Path, *, seconds: float) -> None:
    import subprocess

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={seconds}",
        "-c:a", "libmp3lame",
        "-t", str(seconds),
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]


def test_retime_video_doubles_duration_at_half_speed(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    dst = tmp_path / "dst.mp4"
    _make_silent_clip(src, seconds=2.0)
    df._retime_video(src, dst, speed_factor=0.5)
    # ffprobe duration of slowed clip should be ~2x the source.
    src_dur = df._probe_video_duration_sec(src)
    dst_dur = df._probe_video_duration_sec(dst)
    assert src_dur is not None and dst_dur is not None
    assert dst_dur == pytest.approx(src_dur * 2.0, rel=0.1)


def test_retime_video_passthrough_at_unit_speed(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    dst = tmp_path / "dst.mp4"
    _make_silent_clip(src, seconds=1.0)
    df._retime_video(src, dst, speed_factor=1.0)
    assert dst.exists()
    src_dur = df._probe_video_duration_sec(src)
    dst_dur = df._probe_video_duration_sec(dst)
    assert dst_dur == pytest.approx(src_dur, rel=0.05)


def test_retime_video_rejects_non_positive_speed(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    dst = tmp_path / "dst.mp4"
    _make_silent_clip(src, seconds=1.0)
    with pytest.raises(RuntimeError, match="playback_speed_factor must be > 0"):
        df._retime_video(src, dst, speed_factor=0.0)


def test_mux_audio_padded_keeps_video_length(tmp_path: Path) -> None:
    """Padded mux must preserve full video duration even when audio is shorter."""
    video = tmp_path / "video.mp4"
    audio = tmp_path / "narration.mp3"
    out = tmp_path / "out.mp4"
    _make_silent_clip(video, seconds=4.0)
    _make_silent_audio(audio, seconds=1.0)
    df._mux_audio_padded(video, audio, out)
    out_dur = df._probe_video_duration_sec(out)
    assert out_dur is not None
    # Final length matches the (longer) video, not the (shorter) audio.
    assert out_dur == pytest.approx(4.0, abs=0.3)


# NOTE: ``_compose_action_audio`` and ``_generate_action_narration`` were
# removed when the narration pipeline collapsed to a single audio-driven path
# (one TTS pass + Whisper word timings → freeze-padded video, mux as the last
# step). See :func:`docgen.demo_function._align_visual_to_narration` and
# :mod:`docgen.pf_align` for the replacement; alignment behavior is exercised
# directly in ``tests/test_pf_align.py``.


# ---------------------------------------------------------------------------
# manifest.json snapshot exposes timeline-related fields
# ---------------------------------------------------------------------------


def test_snapshot_includes_speed_factor_and_actions(tmp_path: Path, monkeypatch) -> None:
    """``manifest.json`` carries playback_speed_factor + action snapshot + (empty) timeline for cli kind."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tape = tmp_path / "demo.tape"
    tape.write_text(
        'Output rendered/cli-demo.mp4\n'
        "Set Shell bash\n"
        "Set Width 320\n"
        "Set Height 240\n"
        "Sleep 200ms\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "m.docgen.yaml"
    manifest_path.write_text(
        _yaml_manifest_text(
            demonstration={"kind": "cli", "tape": "demo.tape"},
            output_budget={
                "duration_seconds": 10,
                "resolution": "1280x720",
                "playback_speed_factor": 0.75,
            },
        ),
        encoding="utf-8",
    )
    m = load_manifest(manifest_path)
    out_dir = tmp_path / "out"
    df.render(m, out_dir, no_narration=True)
    snapshot = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert snapshot["playback_speed_factor"] == 0.75
    assert snapshot["actions"] == []
    assert snapshot["timeline"] == []
