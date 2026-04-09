"""Tests for docgen.manim_runner — quality flag parsing and binary discovery."""

import tempfile
from pathlib import Path

import yaml

from docgen.config import Config
from docgen.manim_runner import ManimRunner, _width_for_height


def _make_config(quality: str = "720p30") -> Config:
    cfg_path = Path(tempfile.mktemp(suffix=".yaml"))
    cfg_path.write_text(yaml.dump({"manim": {"quality": quality}}), encoding="utf-8")
    try:
        return Config.from_yaml(cfg_path)
    finally:
        cfg_path.unlink(missing_ok=True)


class TestQualityFlags:
    def test_720p30_preset(self):
        runner = ManimRunner(_make_config("720p30"))
        assert runner._quality_flags() == ["-qm"]

    def test_1080p60_preset(self):
        runner = ManimRunner(_make_config("1080p60"))
        assert runner._quality_flags() == ["-qh"]

    def test_480p15_preset(self):
        runner = ManimRunner(_make_config("480p15"))
        assert runner._quality_flags() == ["-ql"]

    def test_2160p60_preset(self):
        runner = ManimRunner(_make_config("2160p60"))
        assert runner._quality_flags() == ["-qp"]

    def test_1080p30_custom(self):
        runner = ManimRunner(_make_config("1080p30"))
        flags = runner._quality_flags()
        assert "--resolution" in flags
        assert "1920,1080" in flags
        assert "--frame_rate" in flags
        assert "30" in flags

    def test_1440p60_custom(self):
        runner = ManimRunner(_make_config("1440p60"))
        flags = runner._quality_flags()
        assert "--resolution" in flags
        assert "2560,1440" in flags
        assert "60" in flags

    def test_unknown_falls_back_with_warning(self, capsys):
        runner = ManimRunner(_make_config("banana"))
        flags = runner._quality_flags()
        assert flags == ["-qm"]
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "banana" in captured.out


class TestQualitySubdir:
    def test_preset_subdir(self):
        runner = ManimRunner(_make_config("720p30"))
        assert runner.quality_subdir() == "720p30"

    def test_custom_subdir(self):
        runner = ManimRunner(_make_config("1080p30"))
        assert runner.quality_subdir() == "1080p30"

    def test_unknown_subdir_defaults(self):
        runner = ManimRunner(_make_config("banana"))
        assert runner.quality_subdir() == "720p30"


class TestWidthForHeight:
    def test_1080(self):
        assert _width_for_height(1080) == 1920

    def test_720(self):
        assert _width_for_height(720) == 1280

    def test_1440(self):
        assert _width_for_height(1440) == 2560

    def test_480(self):
        assert _width_for_height(480) == 854
