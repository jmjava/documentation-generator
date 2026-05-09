"""Tests for docgen.yaml_generate (deterministic parts only)."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.config import Config
from docgen.yaml_generate import (
    discover_visual_map,
    manim_scene_class_names_in_order,
    merge_defaults,
    narration_not_in_segments,
    narration_segment_pairs,
    segments_in_config,
)


def _cfg(tmp_path: Path, raw: dict) -> Config:
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(p)


def _minimal_cfg(tmp_path: Path) -> Config:
    return _cfg(
        tmp_path,
        {
            "repo_root": ".",
            "dirs": {
                "narration": "narration",
                "audio": "audio",
                "animations": "animations",
                "terminal": "terminal",
                "recordings": "recordings",
            },
            "segments": {"all": ["01"], "default": ["01"]},
            "visual_map": {"01": {"type": "vhs", "source": "x.mp4"}},
            "discovery": {"auto_visual_map": False},
        },
    )


def test_narration_segment_pairs_skips_readme(tmp_path: Path) -> None:
    nd = tmp_path / "narration"
    nd.mkdir()
    (nd / "README.md").write_text("x")
    (nd / "01-foo.md").write_text("a")
    (nd / "bad.md").write_text("b")
    pairs = narration_segment_pairs(nd)
    assert pairs == [("01", "01-foo")]


def test_narration_not_in_segments(tmp_path: Path) -> None:
    nd = tmp_path / "narration"
    nd.mkdir()
    (nd / "09-new.md").write_text("x")
    raw = {"segments": {"all": ["01", "02"]}}
    gaps = narration_not_in_segments(raw, nd)
    assert gaps == [("09", "09-new")]


def test_merge_defaults_adds_archive_exclude(tmp_path: Path) -> None:
    raw: dict = {"wizard": {"exclude_patterns": ["**/node_modules/**"]}}
    cfg = _minimal_cfg(tmp_path)
    ch = merge_defaults(raw, cfg)
    assert any("archive" in c for c in ch)
    assert "**/archive/**" in raw["wizard"]["exclude_patterns"]


def test_merge_defaults_idempotent_archive(tmp_path: Path) -> None:
    raw = {"wizard": {"exclude_patterns": ["**/archive/**"]}}
    cfg = _minimal_cfg(tmp_path)
    ch = merge_defaults(raw, cfg)
    assert not any("archive" in x and "added" in x for x in ch)


def test_merge_defaults_syncs_manim_segments_from_visual_map(tmp_path: Path) -> None:
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01", "02"], "default": ["01"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {
            "01": {"type": "manim", "scene": "FooScene"},
            "02": {"type": "vhs", "tape": "x.tape", "source": "x.mp4"},
        },
        "manim_scene_generation": {
            "model": "gpt-4o",
            "segments": {"01": {"class_name": "StaleScene"}},
        },
    }
    cfg = _cfg(tmp_path, raw)
    ch = merge_defaults(raw, cfg)
    assert any("synced from visual_map" in c for c in ch)
    assert raw["manim_scene_generation"]["segments"] == {"01": {"class_name": "FooScene"}}


def test_merge_defaults_manim_segment_sync_idempotent(tmp_path: Path) -> None:
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {"01": {"type": "manim", "scene": "FooScene"}},
        "manim": {"scenes": ["FooScene"]},
        "manim_scene_generation": {
            "model": "gpt-4o",
            "segments": {"01": {"class_name": "FooScene"}},
        },
    }
    cfg = _cfg(tmp_path, raw)
    ch = merge_defaults(raw, cfg)
    assert not any("synced from visual_map" in c for c in ch)


def test_segments_in_config_reads_all_alias(tmp_path: Path) -> None:
    raw = {"segments": {"all": ["03", "04"], "default": ["01"]}}
    assert segments_in_config(raw) == {"03", "04"}


def test_manim_scene_class_names_in_order(tmp_path: Path) -> None:
    ad = tmp_path / "animations"
    ad.mkdir()
    (ad / "scenes.py").write_text(
        "class ASpeedScene(Scene):\n    pass\n# noise\nclass BDemoScene(Scene):\n    pass\n",
        encoding="utf-8",
    )
    assert manim_scene_class_names_in_order(ad / "scenes.py") == ["ASpeedScene", "BDemoScene"]


def test_discover_visual_map_vhs_tape(tmp_path: Path) -> None:
    (tmp_path / "terminal").mkdir()
    (tmp_path / "terminal" / "01-intro.tape").write_text("Output demo.mp4\n", encoding="utf-8")
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-intro"},
        "visual_map": {},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    ch = discover_visual_map(raw, cfg)
    assert ch
    assert raw["visual_map"]["01"] == {
        "type": "vhs",
        "tape": "01-intro.tape",
        "source": "01-intro.mp4",
    }


def test_discover_visual_map_playwright_script(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "segment_07_capture.py").write_text("# pw\n", encoding="utf-8")
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["07"], "default": ["07"]},
        "segment_names": {"07": "07-browser"},
        "visual_map": {},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    discover_visual_map(raw, cfg)
    vm07 = raw["visual_map"]["07"]
    assert vm07["type"] == "playwright"
    assert vm07["script"] == "scripts/segment_07_capture.py"
    assert vm07["source"] == "07-browser.mp4"


def test_discover_visual_map_omits_manim_when_no_scene_classes(tmp_path: Path) -> None:
    (tmp_path / "animations").mkdir()
    (tmp_path / "animations" / "scenes.py").write_text("# no Scene classes yet\n", encoding="utf-8")
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-intro"},
        "visual_map": {},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    discover_visual_map(raw, cfg)
    assert raw["visual_map"] == {}


def test_discover_visual_map_manim_classes_in_order(tmp_path: Path) -> None:
    (tmp_path / "animations").mkdir()
    (tmp_path / "animations" / "scenes.py").write_text(
        "class FirstScene(Scene):\n    pass\nclass SecondScene(Scene):\n    pass\n",
        encoding="utf-8",
    )
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01", "02"], "default": ["01", "02"]},
        "segment_names": {"01": "01-a", "02": "02-b"},
        "visual_map": {},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    discover_visual_map(raw, cfg)
    assert raw["visual_map"]["01"]["type"] == "manim"
    assert raw["visual_map"]["01"]["scene"] == "FirstScene"
    assert raw["visual_map"]["02"]["scene"] == "SecondScene"


def test_discover_visual_map_manim_assigns_only_when_classes_available(tmp_path: Path) -> None:
    (tmp_path / "animations").mkdir()
    (tmp_path / "animations" / "scenes.py").write_text(
        "class OnlyScene(Scene):\n    pass\n",
        encoding="utf-8",
    )
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01", "02"], "default": ["01", "02"]},
        "segment_names": {"01": "01-a", "02": "02-b"},
        "visual_map": {},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    discover_visual_map(raw, cfg)
    assert raw["visual_map"]["01"]["scene"] == "OnlyScene"
    assert "02" not in raw["visual_map"]


def test_discover_visual_map_skipped_when_disabled(tmp_path: Path) -> None:
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {"01": {"type": "manim", "scene": "KeepScene", "source": "KeepScene.mp4"}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    assert discover_visual_map(raw, cfg) == []
    assert raw["visual_map"]["01"]["scene"] == "KeepScene"


def test_merge_defaults_syncs_manim_scenes_list_in_segment_order(tmp_path: Path) -> None:
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"all": ["02", "01"], "default": ["02", "01"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {
            "01": {"type": "manim", "scene": "ZedScene"},
            "02": {"type": "manim", "scene": "AlphaScene"},
        },
        "manim": {"scenes": []},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    merge_defaults(raw, cfg)
    assert raw["manim"]["scenes"] == ["AlphaScene", "ZedScene"]
