"""Tests for Manim runner quality parsing and binary resolution."""

from __future__ import annotations

from pathlib import Path

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
    assert args == ["-pqm"]
    assert "720p30" in label


def test_quality_unknown_falls_back(tmp_path: Path) -> None:
    cfg = _config_with_quality(tmp_path, "banana")
    runner = ManimRunner(cfg)
    args, _label = runner._quality_args()
    assert args == ["-pqm"]


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
