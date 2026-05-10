"""Tests for compose configuration behavior and source discovery."""

from __future__ import annotations

import os
import time
from pathlib import Path

import yaml

from docgen.compose import Composer, filter_segments_by_visual_types
from docgen.config import Config


def _write_cfg(tmp_path: Path, cfg: dict) -> Config:
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


def test_manim_source_uses_configured_quality_dir(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
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


def test_manim_path_derives_mp4_from_class_when_source_missing(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "manim", "class": "IntroScene"}},
        "manim": {"quality": "720p30"},
    }
    c = _write_cfg(tmp_path, cfg)
    target = tmp_path / "animations" / "media" / "videos" / "scenes" / "720p30"
    target.mkdir(parents=True, exist_ok=True)
    (target / "IntroScene.mp4").write_text("x", encoding="utf-8")

    composer = Composer(c)
    resolved = composer._manim_path(c.visual_map["01"])
    assert resolved == target / "IntroScene.mp4"


def test_compose_skips_unmapped_segment(tmp_path: Path, capsys) -> None:
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {},
        "manim": {"quality": "1080p30"},
    }
    c = _write_cfg(tmp_path, cfg)
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    n = Composer(c).compose_segments(["01"], strict=True)
    assert n == 0
    out = capsys.readouterr().out
    assert "unmapped" in out
    assert "SKIP: no visual_map" in out


def test_stale_visual_warning_when_video_older_than_audio(tmp_path: Path, capsys, monkeypatch) -> None:
    """Compose should warn when visual file is older than audio file."""
    cfg = {
        "dirs": {"audio": "audio", "recordings": "recordings", "animations": "animations"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
        "manim": {"quality": "1080p30"},
    }
    c = _write_cfg(tmp_path, cfg)
    audio = tmp_path / "audio" / "01-demo.mp3"
    target = tmp_path / "animations" / "media" / "videos" / "scenes" / "1080p30"
    target.mkdir(parents=True, exist_ok=True)
    video = target / "Scene01.mp4"
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


def test_filter_segments_by_visual_types_respects_visual_map(tmp_path: Path) -> None:
    cfg = {
        "dirs": {
            "animations": "animations",
            "audio": "audio",
            "recordings": "recordings",
        },
        "segments": {"default": ["01", "06", "10"], "all": ["01", "06", "10"]},
        "visual_map": {
            "01": {"type": "manim"},
            "06": {"type": "still"},
            "10": {"type": "still"},
        },
    }
    c = _write_cfg(tmp_path, cfg)
    assert filter_segments_by_visual_types(c, ["01", "06"], ("still",)) == ["06"]
    assert filter_segments_by_visual_types(c, c.segments_default, ("still",)) == [
        "06",
        "10",
    ]
    assert filter_segments_by_visual_types(c, ["01", "06"], ()) == ["01", "06"]
    assert filter_segments_by_visual_types(c, ["01", "06"], None) == ["01", "06"]
