"""Tests for compose configuration behavior and source discovery."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from docgen.compose import ComposeError, Composer
from docgen.config import Config
from docgen.playwright_runner import PlaywrightError


def _write_cfg(tmp_path: Path, cfg: dict) -> Config:
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


def test_manim_source_uses_configured_quality_dir(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "terminal": "terminal", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
        "manim": {"quality": "1080p30"},
    }
    c = _write_cfg(tmp_path, cfg)
    target = tmp_path / "animations" / "media" / "videos" / "scenes" / "1080p30"
    target.mkdir(parents=True, exist_ok=True)
    (target / "Scene01.mp4").write_text("x", encoding="utf-8")

    composer = Composer(c)
    resolved = composer._manim_path(c.visual_map["01"])
    assert resolved == target / "Scene01.mp4"


def test_compose_freeze_playwright_uses_higher_effective_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Playwright + TTS: ratio above default 0.25 but below 0.45 must compose (issue #55)."""
    cfg = {
        "dirs": {"terminal": "terminal", "audio": "audio", "recordings": "recordings", "animations": "animations"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "vhs", "source": "01-demo.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    audio = tmp_path / "audio" / "01-demo.mp3"
    video = tmp_path / "terminal" / "rendered" / "01-demo.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    audio.parent.mkdir(parents=True, exist_ok=True)
    video.write_text("video", encoding="utf-8")
    audio.write_text("audio", encoding="utf-8")

    def _probe(p: Path) -> float:
        if p.suffix == ".mp3":
            return 44.0
        return 30.0

    composer = Composer(c)
    monkeypatch.setattr(composer, "_probe_duration", _probe)
    monkeypatch.setattr(composer, "_run_ffmpeg", lambda _cmd: None)
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    assert composer._compose_simple("01", video, strict=True, visual_type="playwright") is True

    with pytest.raises(ComposeError, match="FREEZE GUARD"):
        composer._compose_simple("01", video, strict=True, visual_type="vhs")


def test_stale_visual_warning_when_video_older_than_audio(tmp_path: Path, capsys, monkeypatch) -> None:
    """Compose should warn when visual file is older than audio file."""
    cfg = {
        "dirs": {"terminal": "terminal", "audio": "audio", "recordings": "recordings", "animations": "animations"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "vhs", "source": "01-demo.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    audio = tmp_path / "audio" / "01-demo.mp3"
    video = tmp_path / "terminal" / "rendered" / "01-demo.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    audio.parent.mkdir(parents=True, exist_ok=True)
    video.write_text("video", encoding="utf-8")
    audio.write_text("audio", encoding="utf-8")
    now = time.time()
    os.utime(video, (now - 100, now - 100))
    os.utime(audio, (now, now))

    composer = Composer(c)
    monkeypatch.setattr(composer, "_probe_duration", lambda _p: 10.0)
    monkeypatch.setattr(composer, "_run_ffmpeg", lambda _cmd: None)
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    composer._compose_simple("01", video, strict=False)
    out = capsys.readouterr().out
    assert "visual may be stale" in out


def test_stale_vhs_warning_printed(tmp_path: Path, capsys) -> None:
    cfg = {
        "dirs": {"terminal": "terminal", "audio": "audio", "recordings": "recordings", "animations": "animations"},
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "vhs", "source": "01-demo.mp4", "tape": "01-demo.tape"}},
        "compose": {"warn_stale_vhs": True},
    }
    c = _write_cfg(tmp_path, cfg)
    tape = tmp_path / "terminal" / "01-demo.tape"
    video = tmp_path / "terminal" / "rendered" / "01-demo.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    tape.parent.mkdir(parents=True, exist_ok=True)
    tape.write_text("Type \"echo hi\"\n", encoding="utf-8")
    video.write_text("video", encoding="utf-8")
    # Ensure tape is newer than rendered video.
    now = time.time()
    os.utime(video, (now - 10, now - 10))
    os.utime(tape, (now, now))

    composer = Composer(c)
    composer._warn_if_stale_vhs(c.visual_map["01"], video)
    out = capsys.readouterr().out
    assert "tape is newer" in out


def test_stale_vhs_warning_can_be_disabled(tmp_path: Path, capsys) -> None:
    cfg = {
        "dirs": {"terminal": "terminal", "audio": "audio", "recordings": "recordings", "animations": "animations"},
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "vhs", "source": "01-demo.mp4", "tape": "01-demo.tape"}},
        "compose": {"warn_stale_vhs": False},
    }
    c = _write_cfg(tmp_path, cfg)
    tape = tmp_path / "terminal" / "01-demo.tape"
    video = tmp_path / "terminal" / "rendered" / "01-demo.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    tape.parent.mkdir(parents=True, exist_ok=True)
    tape.write_text("Type \"echo hi\"\n", encoding="utf-8")
    video.write_text("video", encoding="utf-8")
    tape.touch()

    composer = Composer(c)
    composer._warn_if_stale_vhs(c.visual_map["01"], video)
    out = capsys.readouterr().out
    assert out == ""


def test_playwright_source_resolves_to_rendered_path(tmp_path: Path) -> None:
    cfg = {
        "dirs": {
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
            "animations": "animations",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "playwright", "source": "01-browser.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    rendered = tmp_path / "terminal" / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    expected = rendered / "01-browser.mp4"
    expected.write_text("video", encoding="utf-8")

    composer = Composer(c)
    resolved = composer._playwright_path(c.visual_map["01"])
    assert resolved == expected


def test_compose_playwright_runs_capture_when_source_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = {
        "dirs": {
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
            "animations": "animations",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {
            "01": {
                "type": "playwright",
                "source": "01-browser.mp4",
                "script": "scripts/capture.py",
            }
        },
    }
    c = _write_cfg(tmp_path, cfg)
    audio = tmp_path / "audio" / "01-demo.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"mp3")

    rendered = tmp_path / "terminal" / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    expected_video = rendered / "01-browser.mp4"

    calls: list[str] = []

    class FakeRunner:
        def __init__(self, _config) -> None:
            pass

        def capture_segment(self, seg_id: str, vmap: dict) -> Path:
            calls.append(seg_id)
            expected_video.write_bytes(b"video")
            return expected_video

    monkeypatch.setattr("docgen.playwright_runner.PlaywrightRunner", FakeRunner)

    composer = Composer(c)
    monkeypatch.setattr(composer, "_probe_duration", lambda _p: 10.0)
    monkeypatch.setattr(composer, "_run_ffmpeg", lambda _cmd: None)
    ok = composer.compose_segments(["01"], strict=True)
    assert ok == 1
    assert calls == ["01"]


def test_playwright_test_video_path_repo_relative(tmp_path: Path) -> None:
    cfg = {
        "dirs": {
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
            "animations": "animations",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {
            "01": {"type": "playwright_test", "test": "e2e/foo.spec.ts", "source": "test-results/v/run.webm"},
        },
    }
    c = _write_cfg(tmp_path, cfg)
    rel = tmp_path / "test-results" / "v" / "run.webm"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text("webm", encoding="utf-8")

    composer = Composer(c)
    resolved = composer._playwright_test_video_path(c.visual_map["01"])
    assert resolved == rel


def test_playwright_test_video_path_terminal_rendered_fallback(tmp_path: Path) -> None:
    cfg = {
        "dirs": {
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
            "animations": "animations",
        },
        "segments": {"default": ["03"], "all": ["03"]},
        "visual_map": {
            "03": {
                "type": "playwright_test",
                "test": "tests/e2e/test_demo.py::test_flow",
                "source": "videos/demo.webm",
            },
        },
    }
    c = _write_cfg(tmp_path, cfg)
    vid = tmp_path / "terminal" / "rendered" / "videos" / "demo.webm"
    vid.parent.mkdir(parents=True, exist_ok=True)
    vid.write_text("webm", encoding="utf-8")

    composer = Composer(c)
    resolved = composer._playwright_test_video_path(c.visual_map["03"])
    assert resolved == vid


def test_compose_playwright_test_muxes_existing_video(tmp_path: Path, monkeypatch) -> None:
    cfg = {
        "dirs": {
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
            "animations": "animations",
        },
        "segments": {"default": ["03"], "all": ["03"]},
        "segment_names": {"03": "03-demo"},
        "visual_map": {
            "03": {
                "type": "playwright_test",
                "test": "tests/e2e/test_demo.py::test_flow",
                "source": "videos/demo.webm",
            },
        },
    }
    c = _write_cfg(tmp_path, cfg)
    vid = tmp_path / "terminal" / "rendered" / "videos" / "demo.webm"
    vid.parent.mkdir(parents=True, exist_ok=True)
    vid.write_bytes(b"webm")
    audio = tmp_path / "audio" / "03-demo.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"mp3")

    composer = Composer(c)
    monkeypatch.setattr(composer, "_probe_duration", lambda _p: 10.0)
    monkeypatch.setattr(composer, "_run_ffmpeg", lambda _cmd: None)
    ok = composer.compose_segments(["03"], strict=True)
    assert ok == 1


def test_compose_playwright_skip_on_capture_error(tmp_path: Path, monkeypatch) -> None:
    cfg = {
        "dirs": {
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
            "animations": "animations",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {
            "01": {
                "type": "playwright",
                "source": "01-browser.mp4",
                "script": "scripts/capture.py",
            }
        },
    }
    c = _write_cfg(tmp_path, cfg)

    class FakeRunner:
        def __init__(self, _config) -> None:
            pass

        def capture_segment(self, seg_id: str, vmap: dict) -> Path:
            raise PlaywrightError("boom")

    monkeypatch.setattr("docgen.playwright_runner.PlaywrightRunner", FakeRunner)
    composer = Composer(c)
    ok = composer.compose_segments(["01"], strict=True)
    assert ok == 0
