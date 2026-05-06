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
        assert c.warn_stale_vhs is True
        assert c.manim_path is None
        assert c.vhs_path is None
        assert c.vhs_render_timeout_sec == 120
        assert c.playwright_python_path is None
        assert c.playwright_timeout_sec == 120
        assert c.playwright_default_url is None
        assert c.playwright_default_viewport == (1920, 1080)
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
        "vhs": {
            "vhs_path": "/opt/bin/vhs",
            "sync_from_timing": True,
            "typing_ms_per_char": 40,
            "render_timeout_sec": 240,
        },
        "compose": {"ffmpeg_timeout_sec": 900, "warn_stale_vhs": False},
        "pipeline": {"sync_vhs_after_timestamps": True},
        "playwright": {
            "python_path": "/opt/bin/python3",
            "timeout_sec": 240,
            "default_url": "http://localhost:3300",
            "default_viewport": {"width": 1366, "height": 768},
        },
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
    assert c.playwright_python_path == "/opt/bin/python3"
    assert c.playwright_timeout_sec == 240
    assert c.playwright_default_url == "http://localhost:3300"
    assert c.playwright_default_viewport == (1366, 768)


def test_playwright_test_speed_factor_defaults(tmp_path):
    p = tmp_path / "docgen.yaml"
    p.write_text("{}", encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.playwright_test_min_speed_factor == 0.25
    assert c.playwright_test_max_speed_factor == 4.0


def test_playwright_test_speed_factor_overrides(tmp_path):
    cfg = {"playwright_test": {"min_speed_factor": 0.3, "max_speed_factor": 3.5}}
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(p)
    assert c.playwright_test_min_speed_factor == 0.3
    assert c.playwright_test_max_speed_factor == 3.5


def test_minimal_config(tmp_path):
    c = Config.minimal(tmp_path)
    assert c.base_dir == tmp_path.resolve()
    assert c.terminal_dir == c.base_dir / "terminal"


def test_catalog_file_path_default_is_repo_root(tmp_path):
    """Catalog defaults to repo root so it stays stable if docgen.yaml lives in a subdir."""
    (tmp_path / ".git").mkdir()
    demos = tmp_path / "docs" / "demos"
    demos.mkdir(parents=True)
    (demos / "docgen.yaml").write_text("{}", encoding="utf-8")
    c = Config.from_yaml(demos / "docgen.yaml")
    assert c.catalog_file_path == (tmp_path / "docgen.catalog.yaml").resolve()


def test_catalog_file_path_override_relative_to_repo_root(tmp_path):
    (tmp_path / ".git").mkdir()
    demos = tmp_path / "docs" / "demos"
    demos.mkdir(parents=True)
    cfg = {"catalog": {"file": "metadata/docgen-catalog.yaml"}}
    (demos / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(demos / "docgen.yaml")
    assert c.catalog_file_path == (tmp_path / "metadata" / "docgen-catalog.yaml").resolve()


def test_catalog_file_path_override_absolute(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "my-catalog.yaml"
    demos = tmp_path / "docs" / "demos"
    demos.mkdir(parents=True)
    cfg = {"catalog": {"file": str(target)}}
    (demos / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(demos / "docgen.yaml")
    assert c.catalog_file_path == target.resolve()


def test_discover_tests_scan_roots_default(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump({"segments": {"default": ["01"], "all": ["01"]}}),
        encoding="utf-8",
    )
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.discover_tests_scan_roots == [tmp_path.resolve()]


def test_discover_tests_scan_roots_monorepo(tmp_path):
    (tmp_path / ".git").mkdir()
    apps = tmp_path / "apps" / "web"
    apps.mkdir(parents=True)
    cfg = {
        "segments": {"default": ["01"], "all": ["01"]},
        "discover_tests": {"roots": [".", "apps/web"]},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.discover_tests_scan_roots == [tmp_path.resolve(), apps.resolve()]


def test_pipeline_manim_scene_names_from_visual_map(tmp_path):
    cfg = {
        "segments": {"all": ["01", "07", "03"]},
        "visual_map": {
            "01": {"type": "manim", "scene": "OverviewScene"},
            "03": {"type": "manim", "scene": "WizardScene"},
            "07": {"type": "playwright_test", "test": "e/x.spec.ts", "source": "v.webm"},
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.pipeline_manim_scene_names() == ["OverviewScene", "WizardScene"]


def test_pipeline_vhs_tape_filenames_from_visual_map(tmp_path):
    cfg = {
        "segments": {"all": ["02", "07"]},
        "visual_map": {
            "02": {"type": "vhs", "tape": "02-init.tape", "source": "02-init.mp4"},
            "07": {"type": "playwright_test", "test": "e/x.spec.ts", "source": "v.webm"},
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.pipeline_vhs_tape_filenames() == ["02-init.tape"]


def test_pipeline_vhs_tape_derives_from_source_when_tape_missing(tmp_path):
    cfg = {
        "segments": {"all": ["02"]},
        "visual_map": {
            "02": {"type": "vhs", "source": "foo-bar.mp4"},
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    c = Config.from_yaml(tmp_path / "docgen.yaml")
    assert c.pipeline_vhs_tape_filenames() == ["foo-bar.tape"]
