"""End-to-end test for ``docgen demo-function``.

Drives the full pipeline against the canonical fixture in
``tests/e2e/demo-function/``:

1. Real Chromium captures the declarative actions against the sibling
   ``demo-page.html`` (loaded via ``file://``).
2. All ``say`` strings are concatenated and sent to OpenAI
   ``gpt-4o-mini-tts`` in ONE pass. Whisper word-level timestamps then
   give us a ``(start_ms, end_ms)`` window for each line inside that
   single MP3.
3. Candidate frames sampled from the recording are passed to the OpenAI
   vision model (``gpt-4o-mini``); it picks ONE frame per narration line
   that best shows the on-screen state being described.
4. Those chosen stills are concatenated into a slideshow MP4 with each
   image held for its line's Whisper-aligned duration; the single MP3
   is muxed underneath as the last step.
5. Snapshot artifacts are written to ``--output-dir``.

Skips (never silent fallback):

- ``OPENAI_API_KEY`` not set — narration is required by the renderer.
- Playwright Chromium not installed.
- ``ffmpeg`` / ``ffprobe`` missing from PATH.

Asserts invariants (not byte equality — TTS / vision / Whisper outputs
are all non-deterministic):

- ``rendered.mp4`` has both a video stream and an audio stream.
- Audio duration matches video duration within 0.3s (this is the core
  sync invariant of the audio-driven slideshow — audio is the master
  clock, video must match).
- Snapshot exposes ``playback_speed_factor`` and per-action ``say``
  round-tripped.
- ``timeline`` is the slideshow's *narration*-shaped timeline (one
  entry per ``say``-having action, NOT one per playwright action),
  with monotonic timestamps.
- Cache hit on a second render proves the cache_key is stable across
  the new TTS+Whisper+vision pipeline.

Run locally::

    OPENAI_API_KEY=sk-... pytest tests/e2e/test_demo_function_e2e.py -v

The subprocess env includes tighter keyframe sampling
(``DOCGEN_KEYFRAME_MAX_COUNT`` / ``DOCGEN_KEYFRAME_INTERVAL_SEC``) so the
single batched vision request carries fewer PNGs than a default production
render, while still exercising the full pipeline.

This test runs in the ``e2e`` GitHub Actions job (see ``.github/workflows/ci.yml``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from docgen import demo_function as df

FIXTURE_DIR = Path(__file__).parent / "demo-function"
URL_PLACEHOLDER = "file://__FIXTURE__/demo-page.html"

# Batched vision sends one request with every candidate PNG; cap count + widen
# sampling interval so e2e uses fewer image tokens than a production render.
_E2E_SUBPROCESS_ENV: dict[str, str] = {
    "DOCGEN_KEYFRAME_MAX_COUNT": "12",
    "DOCGEN_KEYFRAME_INTERVAL_SEC": "0.55",
}


def _render_in_subprocess(
    manifest_path: Path,
    out_dir: Path,
    *,
    cache_dir: Path | None = None,
    no_narration: bool = False,
    env_extra: dict[str, str] | None = None,
) -> dict[str, str | int | None]:
    """Run ``df.render`` in a fresh Python interpreter and return its result.

    Why a subprocess and not a direct call? Sibling browser tests in
    ``tests/e2e/`` use ``pytest-playwright``'s session-scoped Playwright
    instance, which keeps an asyncio loop alive on this thread for the
    rest of the run. The renderer's ``_drive_playwright`` opens its own
    ``sync_playwright()`` context which refuses to enter when *any*
    asyncio loop is already running on the calling thread. Running the
    render in a fresh process gives us a clean asyncio context and is
    far cheaper than the alternatives (forked workers, async-API rewrite).

    Returns a dict with ``cache_status`` so the test can assert on it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "_subprocess_result.json"
    cache_arg = (
        f"Path({str(cache_dir)!r})" if cache_dir is not None else "None"
    )
    script = textwrap.dedent(
        f"""
        from pathlib import Path
        import json
        from docgen import demo_function as df

        manifest = df.load_manifest(Path({str(manifest_path)!r}))
        result = df.render(
            manifest,
            Path({str(out_dir)!r}),
            cache_dir={cache_arg},
            no_narration={no_narration!r},
        )
        Path({str(summary_path)!r}).write_text(
            json.dumps({{"cache_status": result.cache_status}}),
            encoding="utf-8",
        )
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, **(env_extra or {})},
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"subprocess render failed (exit {proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout[-1500:]}\n"
            f"STDERR:\n{proc.stderr[-1500:]}"
        )
    return json.loads(summary_path.read_text(encoding="utf-8"))


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
    """Full pipeline: Chromium recording → one-shot TTS + Whisper → vision-LLM
    keyframe slideshow → audio mux."""
    out_dir = tmp_path / "out"
    manifest = df.load_manifest(fixture_manifest_path)

    result = _render_in_subprocess(
        fixture_manifest_path, out_dir, env_extra=_E2E_SUBPROCESS_ENV
    )
    assert result["cache_status"] == "miss"

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

    # The slideshow's timeline is narration-shaped: one entry per
    # ``say``-having action, NOT one per playwright action. Trailing
    # ``wait`` actions with no ``say`` legitimately don't appear because
    # the slideshow only knows about narration lines, not the underlying
    # action kind. ``t_start_ms`` is the Whisper-derived start of the
    # spoken line inside the muxed audio, so captions land at the exact
    # word boundary.
    timeline = snapshot["timeline"]
    assert len(timeline) == len(captioned_actions), (
        f"slideshow timeline has one entry per say; expected "
        f"{len(captioned_actions)}, got {len(timeline)}"
    )
    for entry in timeline:
        assert isinstance(entry.get("say"), str) and entry["say"].strip()
        assert "t_start_ms" in entry
        assert isinstance(entry["t_start_ms"], int)
        assert entry["t_start_ms"] >= 0
        # ``api_name`` is preserved as a soft hint (may be None for non-
        # spec action-list manifests where the action has no api_name).
        assert "api_name" in entry
    starts = [e["t_start_ms"] for e in timeline]
    assert starts == sorted(starts), "timeline starts must be monotonically increasing"
    assert starts[0] >= 0, "first narration line cannot start before t=0"

    # Cache layer: a second render against the same cache_dir should hit the cache
    # (proves cache_key is stable for identical fixture + manifest + speed factor).
    cache_dir = tmp_path / "cache"
    out_dir2 = tmp_path / "out-cached"
    out_dir3 = tmp_path / "out-rerun"
    _render_in_subprocess(
        fixture_manifest_path,
        out_dir2,
        cache_dir=cache_dir,
        env_extra=_E2E_SUBPROCESS_ENV,
    )
    rerun = _render_in_subprocess(
        fixture_manifest_path,
        out_dir3,
        cache_dir=cache_dir,
        env_extra=_E2E_SUBPROCESS_ENV,
    )
    assert rerun["cache_status"] == "hit"


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
