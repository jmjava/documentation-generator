"""Tests for compose configuration behavior and source discovery."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from docgen.compose import ComposeError, Composer, filter_segments_by_visual_types
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


def test_compose_unknown_visual_type_raises(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "vhs", "source": "clip.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    composer = Composer(c)
    with pytest.raises(ComposeError, match="unknown visual_map type 'vhs'"):
        composer.compose_segments(["01"])


def test_cli_compose_unknown_visual_type_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "vhs", "source": "clip.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(c.yaml_path), "compose"])
    assert result.exit_code != 0
    combined = (result.output + result.stderr).lower()
    assert "unknown visual_map type" in combined
    assert "traceback" not in combined


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


def test_find_audio_does_not_use_substring_glob(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "101-other.mp3").write_bytes(b"x")
    composer = Composer(c)
    assert composer._find_audio("01") is None
    (audio / "01-demo.mp3").write_bytes(b"y")
    found = composer._find_audio("01")
    assert found is not None
    assert found.name == "01-demo.mp3"


def test_cli_compose_exits_nonzero_when_nothing_composed(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(c.yaml_path), "compose"])
    assert result.exit_code != 0
    assert "0/" in result.output or "produced" in result.output


def test_cli_compose_falls_back_to_segments_all_when_default_empty(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": [], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(c.yaml_path), "compose"])
    assert result.exit_code != 0
    assert "Composing 1 segments" in result.output


def test_cli_lint_exits_nonzero_when_narration_missing(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    cfg = {
        "dirs": {"narration": "narration"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
    }
    c = _write_cfg(tmp_path, cfg)
    (tmp_path / "narration").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(c.yaml_path), "lint"])
    assert result.exit_code == 1
    assert "no narration file" in result.output


def test_cli_lint_exits_nonzero_when_narration_empty(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    cfg = {
        "dirs": {"narration": "narration"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
    }
    c = _write_cfg(tmp_path, cfg)
    narr = tmp_path / "narration"
    narr.mkdir(parents=True, exist_ok=True)
    (narr / "01-demo.md").write_text("\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(c.yaml_path), "lint"])
    assert result.exit_code == 1
    assert "empty after markdown stripping" in result.output


def test_cli_compose_empty_segments_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": [], "all": []},
        "visual_map": {},
    }
    c = _write_cfg(tmp_path, cfg)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(c.yaml_path), "compose"])
    assert result.exit_code != 0
    assert "no segments to compose" in (result.output + result.stderr).lower()


def test_run_ffmpeg_timeout_with_partial_output_raises(tmp_path: Path, monkeypatch) -> None:
    """A timed-out mux must not count as success just because a partial file exists."""
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    out = tmp_path / "recordings" / "01-demo.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"partial-mux")

    def fake_run(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    composer = Composer(c)
    composer.ffmpeg_timeout_sec = 1
    with pytest.raises(ComposeError, match="removed incomplete 01-demo.mp4"):
        composer._run_ffmpeg(["ffmpeg", "-y", str(out)])
    assert not out.exists()


def test_run_ffmpeg_timeout_without_output_raises(tmp_path: Path, monkeypatch) -> None:
    cfg = {
        "dirs": {"animations": "animations", "audio": "audio", "recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    missing = tmp_path / "recordings" / "missing.mp4"
    missing.parent.mkdir(parents=True, exist_ok=True)

    def fake_run(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=2)

    monkeypatch.setattr(subprocess, "run", fake_run)
    composer = Composer(c)
    composer.ffmpeg_timeout_sec = 2
    with pytest.raises(ComposeError, match="ffmpeg timed out after 2s"):
        composer._run_ffmpeg(["ffmpeg", "-y", str(missing)])
    assert not missing.exists()
