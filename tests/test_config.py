"""Tests for docgen.config."""

import tempfile
from pathlib import Path

import pytest
import yaml

from docgen.config import Config, ConfigError


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


def test_ai_config_defaults_and_override(tmp_path):
    p = tmp_path / "docgen.yaml"
    p.write_text("{}", encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.ai_config["provider"] == "openai"
    p.write_text("ai: {provider: grok}\n", encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.ai_config["provider"] == "grok"


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


def test_find_segment_asset_does_not_match_substring_ids(tmp_path: Path) -> None:
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "101-other.mp3").write_bytes(b"x")
    (audio / "01-intro.mp3").write_bytes(b"y")
    cfg = {
        "segments": {"all": ["01", "101"]},
        "segment_names": {"01": "01-intro", "101": "101-other"},
        "dirs": {"audio": "audio"},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(p)
    found = c.find_segment_asset(audio, "01", ".mp3")
    assert found is not None
    assert found.name == "01-intro.mp3"
    (audio / "01-intro.mp3").unlink()
    assert c.find_segment_asset(audio, "01", ".mp3") is None


def test_from_yaml_invalid_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("segments: [\n  unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        Config.from_yaml(p)


def test_from_yaml_list_root_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        Config.from_yaml(p)


def test_from_yaml_empty_document_is_empty_mapping(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("", encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.raw == {}


def test_from_yaml_null_dirs_uses_defaults(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("dirs: null\nsegments:\n  all: [\"01\"]\n", encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.narration_dir == tmp_path / "narration"
    assert c.segments_all == ["01"]


def test_from_yaml_list_dirs_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("dirs: [narration]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="dirs must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_list_segments_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("segments: [\"01\"]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="segments must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_string_segments_all_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("segments:\n  all: \"01\"\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="segments.all must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_list_validation_ocr_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("validation:\n  ocr: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="validation.ocr must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_string_visual_map_row_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('visual_map:\n  "01": FirstScene\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="visual_map.01 must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_unquoted_segments_all_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("segments:\n  all: [01]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="segments.all\\[0\\] must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_unquoted_visual_map_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("visual_map:\n  01:\n    type: manim\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="visual_map key must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_unquoted_concat_item_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("concat:\n  full: [01]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="concat.full\\[0\\] must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_unquoted_segment_names_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("segment_names:\n  01: 01-intro\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="segment_names key must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_unquoted_pages_segments_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("pages:\n  segments:\n    01:\n      title: Overview\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="pages.segments key must be a YAML string"):
        Config.from_yaml(p)
