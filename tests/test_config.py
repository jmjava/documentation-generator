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
        assert c.manim_quality == "720p30"
        assert c.max_drift_sec == 2.75
        assert c.ocr_config["sample_interval_sec"] == 2
        assert c.ffmpeg_timeout_sec == 300
        assert c.warn_stale_vhs is True
        assert c.manim_path is None
        assert c.vhs_path is None
        assert c.vhs_render_timeout_sec == 120
    finally:
        cfg_path.unlink()


def test_visual_map(tmp_config):
    c = Config.from_yaml(tmp_config)
    assert c.visual_map["01"]["type"] == "manim"


def test_resolved_dirs(tmp_config):
    c = Config.from_yaml(tmp_config)
    assert c.narration_dir == tmp_config.parent / "narration"
    assert c.audio_dir == tmp_config.parent / "audio"


def test_binary_paths_and_compose_config(tmp_path):
    cfg = {
        "manim": {"manim_path": "/opt/bin/manim"},
        "vhs": {
            "vhs_path": "/opt/bin/vhs",
            "sync_from_timing": True,
            "typing_ms_per_char": 40,
            "render_timeout_sec": 240,
        },
        "compose": {"ffmpeg_timeout_sec": 900, "warn_stale_vhs": False},
        "pipeline": {"sync_vhs_after_timestamps": True},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.manim_path == "/opt/bin/manim"
    assert c.vhs_path == "/opt/bin/vhs"
    assert c.ffmpeg_timeout_sec == 900
    assert c.warn_stale_vhs is False
    assert c.sync_from_timing is True
    assert c.sync_vhs_after_timestamps is True
    assert c.typing_ms_per_char == 40
    assert c.vhs_render_timeout_sec == 240
