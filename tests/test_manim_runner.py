"""Tests for Manim runner quality parsing and binary resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from docgen.config import Config
from docgen.manim_runner import ManimRunner


def _config_with_quality(tmp_path: Path, quality: str) -> Config:
    cfg = {
        "dirs": {"animations": "animations"},
        "manim": {"quality": quality, "scenes": ["Scene01"]},
        "segments": {"default": ["01"], "all": ["01"]},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    (tmp_path / "animations").mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(p)


def test_quality_1080p30_maps_to_resolution(tmp_path: Path) -> None:
    cfg = _config_with_quality(tmp_path, "1080p30")
    runner = ManimRunner(cfg)
    args, label = runner._quality_args()
    assert args == ["--resolution", "1920,1080", "--frame_rate", "30"]
    assert "1080p30" in label


def test_quality_720p30_uses_preset_flag(tmp_path: Path) -> None:
    cfg = _config_with_quality(tmp_path, "720p30")
    runner = ManimRunner(cfg)
    args, label = runner._quality_args()
    assert args == ["-qm"]
    assert "720p30" in label


def test_quality_unknown_falls_back(tmp_path: Path) -> None:
    cfg = _config_with_quality(tmp_path, "banana")
    runner = ManimRunner(cfg)
    args, _label = runner._quality_args()
    assert args == ["-qm"]


def test_quality_args_never_include_preview_flag(tmp_path: Path) -> None:
    """-p opens a GUI player; headless servers fail with 'Unable to create a GL context'."""
    for quality in ("480p15", "720p30", "1080p60", "2160p60", "1080p30", "banana"):
        cfg = _config_with_quality(tmp_path, quality)
        args, _label = ManimRunner(cfg)._quality_args()
        assert "-p" not in args
        assert not any(a.startswith("-p") for a in args), (quality, args)


def test_resolve_manim_binary_from_config_path(tmp_path: Path) -> None:
    manim_bin = tmp_path / "tools" / "manim"
    manim_bin.parent.mkdir(parents=True, exist_ok=True)
    manim_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    manim_bin.chmod(0o755)

    cfg = {
        "dirs": {"animations": "animations"},
        "segments": {"default": ["01"], "all": ["01"]},
        "manim": {"quality": "720p30", "scenes": ["Scene01"], "manim_path": "tools/manim"},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    (tmp_path / "animations").mkdir(parents=True, exist_ok=True)

    runner = ManimRunner(Config.from_yaml(p))
    resolved = runner._resolve_manim_binary()
    assert resolved == str(manim_bin.resolve())


def test_render_retries_with_flush_cache_after_failure(tmp_path: Path) -> None:
    cfg = _config_with_quality(tmp_path, "720p30")
    (tmp_path / "animations" / "scenes.py").write_text("# stub\n", encoding="utf-8")
    media = (
        tmp_path
        / "animations"
        / "media"
        / "videos"
        / "scenes"
        / "720p30"
        / "partial_movie_files"
        / "Scene01"
    )
    media.mkdir(parents=True)
    (media / "corrupt.mp4").write_bytes(b"bad")

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    runner = ManimRunner(cfg)
    with (
        patch.object(runner, "_resolve_manim_binary", return_value="manim"),
        patch.object(runner, "_check_font"),
        patch("docgen.manim_runner.subprocess.run", side_effect=fake_run),
    ):
        runner.render(scene="Scene01")

    assert len(calls) == 2
    assert "--flush_cache" not in calls[0]
    assert "--flush_cache" in calls[1]
    assert not media.exists()


def test_render_raises_when_retry_also_fails(tmp_path: Path) -> None:
    cfg = _config_with_quality(tmp_path, "720p30")
    (tmp_path / "animations" / "scenes.py").write_text("# stub\n", encoding="utf-8")

    def always_fail(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(1, cmd)

    runner = ManimRunner(cfg)
    with (
        patch.object(runner, "_resolve_manim_binary", return_value="manim"),
        patch.object(runner, "_check_font"),
        patch("docgen.manim_runner.subprocess.run", side_effect=always_fail),
        pytest.raises(RuntimeError, match="Manim failed for scene"),
    ):
        runner.render(scene="Scene01")
