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


def test_from_yaml_list_pages_segments_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('pages:\n  segments: ["01"]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="pages.segments must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_string_context_paths_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "narration_from_source:\n  context:\n    paths: README.md\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="narration_from_source.context.paths must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_list_nfs_segments_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("narration_from_source:\n  segments: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="narration_from_source.segments must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_string_nfs_segment_row_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'narration_from_source:\n  segments:\n    "01": intro\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="narration_from_source.segments.01 must be a YAML mapping"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_manim_scene_generation_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim_scene_generation: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="manim_scene_generation must be a YAML mapping"):
        Config.from_yaml(p)


def test_from_yaml_string_wizard_exclude_patterns_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("wizard:\n  exclude_patterns: archive\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="wizard.exclude_patterns must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_string_wizard_scan_extensions_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("wizard:\n  scan_extensions: .md\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="wizard.scan_extensions must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_string_ocr_error_patterns_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("validation:\n  ocr:\n    error_patterns: command not found\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="validation.ocr.error_patterns must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_string_av_sync_visual_types_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("validation:\n  av_sync:\n    visual_types: manim\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="validation.av_sync.visual_types must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_string_pre_tts_deny_patterns_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "validation:\n  narration_lint:\n    pre_tts_deny_patterns: edit for voice\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="validation.narration_lint.pre_tts_deny_patterns must be a YAML list"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_post_tts_deny_patterns_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "validation:\n  narration_lint:\n    post_tts_deny_patterns: edit for voice\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="validation.narration_lint.post_tts_deny_patterns must be a YAML list"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_manim_unsafe_unicode_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim:\n  unsafe_unicode: \"\\u2192\"\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="manim.unsafe_unicode must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_list_tts_instructions_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "tts:\n  instructions:\n    - Speak calmly\n    - Pronounce YAML as camel\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="tts.instructions must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_tts_voice_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("tts:\n  voice:\n    - coral\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="tts.voice must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_tts_model_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("tts:\n  model:\n    - gpt-4o-mini-tts\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="tts.model must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_wizard_system_prompt_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "wizard:\n  system_prompt:\n    - Write narration\n    - No markdown\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="wizard.system_prompt must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_wizard_llm_model_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("wizard:\n  llm_model:\n    - gpt-4o\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="wizard.llm_model must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_av_sync_anchor_keywords_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("validation:\n  av_sync:\n    anchor_keywords:\n      - Flask\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="validation.av_sync.anchor_keywords must be a YAML mapping"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_av_sync_anchor_keywords_row_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'validation:\n  av_sync:\n    anchor_keywords:\n      "01": Flask\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="validation.av_sync.anchor_keywords.01 must be a YAML list"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_av_sync_anchor_keyword_item_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'validation:\n  av_sync:\n    anchor_keywords:\n      "01":\n        - Flask\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match=r"validation.av_sync.anchor_keywords.01\[0\] must be a YAML mapping",
    ):
        Config.from_yaml(p)


def test_from_yaml_mapping_av_sync_anchor_keywords_loads(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'validation:\n  av_sync:\n    anchor_keywords:\n      "01":\n'
        "        - keyword: Flask\n          expected_at: 5.0\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(p)
    rows = cfg.av_sync_config["anchor_keywords"]["01"]
    assert rows[0]["keyword"] == "Flask"


def test_from_yaml_list_image_generation_model_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("image_generation:\n  model:\n    - gpt-image-1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="image_generation.model must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_image_generation_size_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("image_generation:\n  size:\n    - 1536x1024\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="image_generation.size must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_image_generation_quality_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("image_generation:\n  quality:\n    - high\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="image_generation.quality must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_ai_provider_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("ai:\n  provider:\n    - openai\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="ai.provider must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_ai_base_url_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("ai:\n  base_url:\n    - https://api.openai.com/v1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="ai.base_url must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_timestamps_engine_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("timestamps:\n  engine:\n    - local\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="timestamps.engine must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_tts_language_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("tts:\n  language:\n    - en\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="tts.language must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_manim_font_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim:\n  font:\n    - Liberation Sans\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="manim.font must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_manim_quality_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim:\n  quality:\n    - 1080p30\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="manim.quality must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_manim_path_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim:\n  manim_path:\n    - /usr/bin/manim\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="manim.manim_path must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_narration_from_source_model_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("narration_from_source:\n  model:\n    - gpt-4o\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="narration_from_source.model must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_narration_from_source_system_prompt_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "narration_from_source:\n  system_prompt:\n    - Write narration\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="narration_from_source.system_prompt must be a YAML string"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_manim_scene_generation_model_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim_scene_generation:\n  model:\n    - gpt-4o\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="manim_scene_generation.model must be a YAML string"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_manim_scene_generation_system_prompt_raises(
    tmp_path: Path,
) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "manim_scene_generation:\n  system_prompt:\n    - Draw boxes\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match="manim_scene_generation.system_prompt must be a YAML string"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_scene_spec_system_prompt_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "manim_scene_generation:\n  scene_spec_system_prompt:\n    - Cover beats\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="manim_scene_generation.scene_spec_system_prompt must be a YAML string",
    ):
        Config.from_yaml(p)


def test_from_yaml_list_visual_map_type_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('visual_map:\n  "01":\n    type:\n      - manim\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="visual_map.01.type must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_visual_map_scene_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'visual_map:\n  "01":\n    type: manim\n    scene:\n      - OverviewScene\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="visual_map.01.scene must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_visual_map_source_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'visual_map:\n  "01":\n    type: still\n    source:\n      - slide.png\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="visual_map.01.source must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_empty_visual_map_type_allowed(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('visual_map:\n  "01":\n    type: ""\n', encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.visual_map["01"]["type"] == ""


def test_from_yaml_list_segment_names_value_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('segment_names:\n  "01":\n    - 01-intro\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="segment_names.01 must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_env_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("env_file:\n  - .env\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="env_file must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_repo_root_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("repo_root:\n  - ..\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="repo_root must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_dirs_narration_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("dirs:\n  narration:\n    - narration\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="dirs.narration must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_nfs_segment_system_prompt_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'narration_from_source:\n  segments:\n    "01":\n      system_prompt:\n'
        "        - Write narration\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="narration_from_source.segments.01.system_prompt must be a YAML string",
    ):
        Config.from_yaml(p)


def test_from_yaml_list_nfs_segment_topic_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'narration_from_source:\n  segments:\n    "01":\n      topic:\n        - Overview\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="narration_from_source.segments.01.topic must be a YAML string",
    ):
        Config.from_yaml(p)


def test_from_yaml_list_msg_segment_class_name_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'manim_scene_generation:\n  segments:\n    "01":\n      class_name:\n'
        "        - OverviewScene\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="manim_scene_generation.segments.01.class_name must be a YAML string",
    ):
        Config.from_yaml(p)


def test_from_yaml_list_msg_segment_scene_spec_prompt_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'manim_scene_generation:\n  segments:\n    "01":\n'
        "      scene_spec_system_prompt:\n        - Cover beats\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="manim_scene_generation.segments.01.scene_spec_system_prompt must be a YAML string",
    ):
        Config.from_yaml(p)


def test_from_yaml_empty_nfs_segment_system_prompt_allowed(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'narration_from_source:\n  segments:\n    "01":\n      system_prompt: ""\n',
        encoding="utf-8",
    )
    c = Config.from_yaml(p)
    assert c.raw["narration_from_source"]["segments"]["01"]["system_prompt"] == ""


def test_from_yaml_list_pages_docs_dir_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("pages:\n  docs_dir:\n    - docs\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="pages.docs_dir must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_pages_title_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("pages:\n  title:\n    - Demo Videos\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="pages.title must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_list_pages_segment_title_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'pages:\n  segments:\n    "01":\n      title:\n        - Overview\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="pages.segments.01.title must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_string_visual_map_sources_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'visual_map:\n  "01":\n    type: mixed\n    sources: clip.mp4\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="visual_map.01.sources must be a YAML list"):
        Config.from_yaml(p)


def test_from_yaml_list_visual_map_sources_item_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'visual_map:\n  "01":\n    type: mixed\n    sources:\n      - - clip.mp4\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError, match=r"visual_map.01.sources\[0\] must be a YAML string"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_wizard_default_guidance_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "wizard:\n  default_guidance:\n    - Keep it spoken\n    - No markdown\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="wizard.default_guidance must be a YAML string"):
        Config.from_yaml(p)


def test_from_yaml_empty_wizard_default_guidance_allowed(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('wizard:\n  default_guidance: ""\n', encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.wizard_config["default_guidance"] == ""


def test_from_yaml_int_auto_visual_map_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("discovery:\n  auto_visual_map: 0\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="discovery.auto_visual_map must be a YAML boolean"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_auto_visual_map_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('discovery:\n  auto_visual_map: "false"\n', encoding="utf-8")
    with pytest.raises(
        ConfigError, match="discovery.auto_visual_map must be a YAML boolean"
    ):
        Config.from_yaml(p)


def test_from_yaml_int_merge_hint_segments_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("discovery:\n  merge_hint_segments: 0\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="discovery.merge_hint_segments must be a YAML boolean"
    ):
        Config.from_yaml(p)


def test_from_yaml_discovery_bools_allowed(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "discovery:\n  auto_visual_map: false\n  merge_hint_segments: true\n",
        encoding="utf-8",
    )
    c = Config.from_yaml(p)
    assert c.raw["discovery"]["auto_visual_map"] is False
    assert c.raw["discovery"]["merge_hint_segments"] is True


def test_from_yaml_list_silence_noise_db_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("timestamps:\n  silence_noise_db:\n    - -35\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="timestamps.silence_noise_db must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_min_silence_sec_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text('timestamps:\n  min_silence_sec: "0.3"\n', encoding="utf-8")
    with pytest.raises(
        ConfigError, match="timestamps.min_silence_sec must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_bool_ffmpeg_timeout_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("compose:\n  ffmpeg_timeout_sec: true\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="compose.ffmpeg_timeout_sec must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_bool_min_font_size_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim:\n  min_font_size: true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="manim.min_font_size must be a YAML number"):
        Config.from_yaml(p)


def test_from_yaml_list_max_drift_sec_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("validation:\n  max_drift_sec:\n    - 2.75\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="validation.max_drift_sec must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_max_freeze_ratio_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("validation:\n  max_freeze_ratio:\n    - 0.25\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="validation.max_freeze_ratio must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_numeric_tunables_allowed(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "timestamps:\n  silence_noise_db: -40\n  min_silence_sec: 0.25\n"
        "manim:\n  min_font_size: 16\n"
        "compose:\n  ffmpeg_timeout_sec: 120\n"
        "validation:\n  max_drift_sec: 3.0\n  max_freeze_ratio: 0.4\n",
        encoding="utf-8",
    )
    c = Config.from_yaml(p)
    assert c.timestamps_config["silence_noise_db"] == -40
    assert c.timestamps_config["min_silence_sec"] == 0.25
    assert c.manim_min_font_size == 16
    assert c.ffmpeg_timeout_sec == 120
    assert c.max_drift_sec == 3.0
    assert c.max_freeze_ratio == 0.4


def test_from_yaml_bool_nfs_temperature_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("narration_from_source:\n  temperature: true\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="narration_from_source.temperature must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_list_nfs_max_context_bytes_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "narration_from_source:\n  max_context_bytes:\n    - 120000\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="narration_from_source.max_context_bytes must be a YAML number",
    ):
        Config.from_yaml(p)


def test_from_yaml_bool_msg_temperature_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text("manim_scene_generation:\n  temperature: true\n", encoding="utf-8")
    with pytest.raises(
        ConfigError, match="manim_scene_generation.temperature must be a YAML number"
    ):
        Config.from_yaml(p)


def test_from_yaml_string_max_whisper_words_raises(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        'manim_scene_generation:\n  max_whisper_words_in_prompt: "0"\n',
        encoding="utf-8",
    )
    with pytest.raises(
        ConfigError,
        match="manim_scene_generation.max_whisper_words_in_prompt must be a YAML number",
    ):
        Config.from_yaml(p)


def test_from_yaml_generation_numeric_tunables_allowed(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        "narration_from_source:\n  temperature: 0.5\n  max_context_bytes: 90000\n"
        "manim_scene_generation:\n  temperature: 0.4\n  max_context_bytes: 80000\n"
        "  max_whisper_segments_in_prompt: 0\n  max_whisper_words_in_prompt: 12\n"
        "  max_whisper_segment_text_chars: 200\n",
        encoding="utf-8",
    )
    c = Config.from_yaml(p)
    assert c.raw["narration_from_source"]["temperature"] == 0.5
    assert c.raw["narration_from_source"]["max_context_bytes"] == 90000
    assert c.raw["manim_scene_generation"]["temperature"] == 0.4
    assert c.raw["manim_scene_generation"]["max_whisper_words_in_prompt"] == 12
