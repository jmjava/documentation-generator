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
