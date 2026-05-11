"""Tests for docgen.config."""

import tempfile
from pathlib import Path

import pytest
import yaml

from docgen.config import Config


@pytest.fixture
def tmp_config(tmp_path):
    cfg = {
        "segments": {"default": ["01", "02"], "all": ["01", "02", "03"]},
        "visual_map": {"01": {"type": "manim", "source": "Scene.mp4"}},
        "tts": {"model": "gpt-4o-mini-tts", "voice": "coral"},
        "validation": {"max_drift_sec": 3.0},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


def test_from_yaml(tmp_config):
    c = Config.from_yaml(tmp_config)
    assert c.segments_default == ["01", "02"]
    assert c.segments_all == ["01", "02", "03"]
    assert c.tts_model == "gpt-4o-mini-tts"
    assert c.max_drift_sec == 3.0


def test_from_yaml_dir(tmp_config):
    c = Config.from_yaml(tmp_config.parent)
    assert c.segments_default == ["01", "02"]


def test_discover(tmp_config):
    sub = tmp_config.parent / "sub" / "deep"
    sub.mkdir(parents=True)
    c = Config.discover(str(sub))
    assert c.yaml_path == tmp_config.resolve()


def test_discover_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        Config.discover(str(tmp_path / "nonexistent"))


def test_defaults():
    cfg_path = Path(tempfile.mktemp(suffix=".yaml"))
    cfg_path.write_text("{}", encoding="utf-8")
    try:
        c = Config.from_yaml(cfg_path)
        assert c.tts_voice == "coral"
        assert c.manim_quality == "1080p30"
        assert c.manim_font == "Liberation Sans"
        assert c.manim_min_font_size == 14
        assert isinstance(c.manim_unsafe_unicode, list)
        assert "\u2192" in c.manim_unsafe_unicode
        assert c.max_drift_sec == 2.75
        assert c.ocr_config["sample_interval_sec"] == 2
        assert c.ffmpeg_timeout_sec == 300
        assert c.manim_path is None
    finally:
        cfg_path.unlink()


def test_visual_map(tmp_config):
    c = Config.from_yaml(tmp_config)
    assert c.visual_map["01"]["type"] == "manim"


def test_resolved_dirs(tmp_config):
    c = Config.from_yaml(tmp_config)
    assert c.narration_dir == tmp_config.parent / "narration"
    assert c.audio_dir == tmp_config.parent / "audio"


def test_manim_font_and_quality_overrides(tmp_path):
    cfg = {
        "manim": {
            "quality": "720p30",
            "font": "DejaVu Sans",
            "min_font_size": 16,
            "unsafe_unicode": ["\u2192"],
        },
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.manim_quality == "720p30"
    assert c.manim_font == "DejaVu Sans"
    assert c.manim_min_font_size == 16
    assert c.manim_unsafe_unicode == ["\u2192"]


def test_binary_paths_and_compose_config(tmp_path):
    cfg = {
        "manim": {"manim_path": "/opt/bin/manim"},
        "compose": {"ffmpeg_timeout_sec": 900},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.manim_path == "/opt/bin/manim"
    assert c.ffmpeg_timeout_sec == 900


def test_effective_max_freeze_ratio_uses_global(tmp_path):
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump({"validation": {"max_freeze_ratio": 0.4}}), encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.effective_max_freeze_ratio("manim") == 0.4
    assert c.effective_max_freeze_ratio(None) == 0.4


def test_minimal_config(tmp_path):
    c = Config.minimal(tmp_path)
    assert c.base_dir == tmp_path.resolve()
    assert c.recordings_dir == c.base_dir / "recordings"


def test_pipeline_manim_scene_names_from_visual_map(tmp_path):
    cfg = {
        "segments": {"all": ["01", "07", "03"]},
        "visual_map": {
            "01": {"type": "manim", "scene": "OverviewScene"},
            "03": {"type": "manim", "scene": "WizardScene"},
            "07": {"type": "still", "source": "v.png"},
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.pipeline_manim_scene_names() == ["OverviewScene", "WizardScene"]


def test_pipeline_manim_scene_names_falls_back_to_visual_map_class(tmp_path):
    cfg = {
        "segments": {"all": ["01", "02", "03"]},
        "visual_map": {
            "01": {"type": "manim", "class": "FromClassScene"},
            "02": {"type": "manim", "scene": "FromSceneScene"},
            "03": {"type": "manim", "scene": "WinsScene", "class": "IgnoredScene"},
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.pipeline_manim_scene_names() == ["FromClassScene", "FromSceneScene", "WinsScene"]
