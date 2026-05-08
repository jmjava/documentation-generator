"""End-to-end test for ``docgen demo-function``.

Drives the full pipeline against the canonical fixture in
``tests/e2e/demo-function/``:

1. Real Chromium captures the declarative actions against the sibling
   ``demo-page.html`` (loaded via ``file://``).
2. The captured clip is retimed by ``output_budget.playback_speed_factor``.
3. Per-action ``say`` strings are sent to OpenAI ``gpt-4o-mini-tts`` and
   the resulting clips are mixed onto the slowed video at their captured
   timestamps; a matching WebVTT track is burned in as captions.
4. Snapshot artifacts are written to ``--output-dir``.

Skips (never silent fallback):

- ``OPENAI_API_KEY`` not set — narration is required by the renderer.
- Playwright Chromium not installed.
- ``ffmpeg`` / ``ffprobe`` missing from PATH.

Asserts invariants (not byte equality — TTS output is non-deterministic):

- ``rendered.mp4`` has both a video stream and an audio stream.
- Audio duration matches video duration within 0.3s (proves padded mux).
- ``timeline`` records one entry per action with monotonic timestamps.
- Snapshot exposes ``playback_speed_factor`` and per-action ``say`` round-tripped.

Run locally::

    OPENAI_API_KEY=sk-... pytest tests/e2e/test_demo_function_e2e.py -v

This test runs in the ``e2e`` GitHub Actions job (see ``.github/workflows/ci.yml``).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from docgen import demo_function as df

FIXTURE_DIR = Path(__file__).parent / "demo-function"
URL_PLACEHOLDER = "file://__FIXTURE__/demo-page.html"


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _chromium_available() -> bool:
    """Return True if Playwright's Chromium binary is installed.

    We don't import ``playwright.sync_api`` here because importing it doesn't
    verify the browser binary itself — only that the SDK is on PATH. The
    actual launch attempt during ``render`` will surface a ``ToolingMissingError``
    if the binary is missing; we skip up front to keep the diagnostic clean.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            executable = pw.chromium.executable_path
            return bool(executable and Path(executable).exists())
    except Exception:
        return False


@pytest.fixture(scope="module")
def fixture_manifest_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Materialize the e2e manifest with a real ``file://`` URL for this run.

    The committed YAML has a placeholder URL so it stays portable; tests
    rewrite it to point at the absolute path of ``demo-page.html`` next door.
    """
    fixture_html = FIXTURE_DIR / "demo-page.html"
    fixture_yaml = FIXTURE_DIR / "lesson.docgen.yaml"
    assert fixture_html.exists(), f"missing committed fixture: {fixture_html}"
    assert fixture_yaml.exists(), f"missing committed fixture: {fixture_yaml}"

    text = fixture_yaml.read_text(encoding="utf-8")
    real_url = f"file://{fixture_html.resolve()}"
    text = text.replace(URL_PLACEHOLDER, real_url)
    out = tmp_path_factory.mktemp("e2e-demo-function") / "lesson.docgen.yaml"
    out.write_text(text, encoding="utf-8")
    return out


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg / ffprobe not on PATH")
@pytest.mark.skipif(not _chromium_available(), reason="Playwright chromium not installed")
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY", "").strip(),
    reason="OPENAI_API_KEY not set; demo-function refuses to emit silent demos",
)
def test_demo_function_real_chromium_with_per_action_narration(
    fixture_manifest_path: Path,
    tmp_path: Path,
) -> None:
    """Full pipeline: Chromium → slowdown → per-action TTS → padded mux."""
    out_dir = tmp_path / "out"
    manifest = df.load_manifest(fixture_manifest_path)

    result = df.render(manifest, out_dir, no_narration=False)

    assert result.cache_status == "miss"

    rendered = out_dir / "rendered.mp4"
    poster = out_dir / "poster.png"
    snapshot_path = out_dir / "manifest.json"
    fragment = out_dir / "fragment.txt"

    for artifact in (rendered, poster, snapshot_path, fragment):
        assert artifact.exists(), f"missing artifact: {artifact.name}"

    head = rendered.read_bytes()[:12]
    assert b"ftyp" in head, "rendered.mp4 must be a real ISO MP4"
    assert poster.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "poster.png must be a real PNG"

    video_dur = df._probe_video_duration_sec(rendered)
    assert video_dur is not None and video_dur > 0
    assert df._video_has_audio_stream(rendered), (
        "rendered.mp4 must contain an audio stream — narration was muxed"
    )
    audio_ms = df._probe_audio_ms(rendered)
    assert audio_ms is not None
    audio_dur = audio_ms / 1000.0
    assert abs(audio_dur - video_dur) < 0.3, (
        f"audio/video duration mismatch: video={video_dur:.3f}s audio={audio_dur:.3f}s "
        f"(padded mux should match within 0.3s)"
    )

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["identifier"] == manifest.identifier
    assert snapshot["playback_speed_factor"] == pytest.approx(0.7, abs=1e-6)
    assert snapshot["narration"] is not None, "narration must be populated when key is set"
    assert snapshot["narration"]["model"] == "gpt-4o-mini-tts"
    assert snapshot["narration"]["voice"] == "coral"
    assert snapshot["narration"]["ms"] > 0

    actions_snapshot = snapshot["actions"]
    assert len(actions_snapshot) == len(manifest.actions)
    captioned_actions = [a for a in actions_snapshot if a.get("say")]
    assert len(captioned_actions) == 5, (
        f"expected 5 actions with `say`, got {len(captioned_actions)}"
    )

    timeline = snapshot["timeline"]
    assert len(timeline) == len(manifest.actions), (
        "one timeline entry per executed action"
    )
    for entry in timeline:
        assert "kind" in entry
        assert "t_start_ms" in entry and "t_end_ms" in entry
        assert entry["t_end_ms"] >= entry["t_start_ms"]
    starts = [e["t_start_ms"] for e in timeline]
    assert starts == sorted(starts), "timeline starts must be monotonically increasing"

    # Cache layer: a second render against the same cache_dir should hit the cache
    # (proves cache_key is stable for identical fixture + manifest + speed factor).
    cache_dir = tmp_path / "cache"
    out_dir2 = tmp_path / "out-cached"
    out_dir3 = tmp_path / "out-rerun"
    df.render(manifest, out_dir2, cache_dir=cache_dir, no_narration=False)
    rerun = df.render(manifest, out_dir3, cache_dir=cache_dir, no_narration=False)
    assert rerun.cache_status == "hit"


def test_demo_function_fail_loud_when_key_missing(
    fixture_manifest_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ``OPENAI_API_KEY`` raises ``ToolingMissingError`` (no silent demo).

    This test does NOT need a Chromium binary or network access — the renderer
    must reject the run *before* any expensive work. Kept fast and deterministic.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    manifest = df.load_manifest(fixture_manifest_path)
    with pytest.raises(df.ToolingMissingError, match=r"OPENAI_API_KEY"):
        df.render(manifest, tmp_path / "out", no_narration=False)
    assert not (tmp_path / "out" / "rendered.mp4").exists(), (
        "fail-loud must not leave a partial rendered.mp4 on disk"
    )
