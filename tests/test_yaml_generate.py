"""Tests for docgen.yaml_generate (deterministic parts only)."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.config import Config
from docgen.yaml_generate import (
    collect_hint_segment_declarations,
    collect_hint_wirings_by_segment,
    discover_visual_map,
    manim_scene_class_names_in_order,
    merge_defaults,
    merge_hint_declared_segments,
    merge_hint_wiring,
    narration_not_in_segments,
    narration_segment_pairs,
    parse_hint_docgen_front_matter,
    parse_hint_segment_declaration,
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
                "recordings": "recordings",
            },
            "segments": {"all": ["01"], "default": ["01"]},
            "visual_map": {"01": {"type": "manim", "source": "x.mp4"}},
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
            "recordings": "recordings",
        },
        "segments": {"all": ["01", "02"], "default": ["01"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {
            "01": {"type": "manim", "scene": "FooScene"},
            "02": {"type": "still", "source": "x.png"},
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


def test_discover_visual_map_omits_manim_when_no_scene_classes(tmp_path: Path) -> None:
    (tmp_path / "animations").mkdir()
    (tmp_path / "animations" / "scenes.py").write_text("# no Scene classes yet\n", encoding="utf-8")
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
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


def test_parse_hint_segment_declaration_requires_create_true(tmp_path: Path) -> None:
    h = tmp_path / "hints"
    h.mkdir()
    (h / "seg.md").write_text(
        "---\ndocgen:\n  segment:\n    create: false\n    id: \"05\"\n    stem: 05-x\n---\n\nbody\n",
        encoding="utf-8",
    )
    assert parse_hint_segment_declaration(h / "seg.md") is None
    (h / "ok.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: 5\n    stem: 05-from-hints\n---\n\nx\n",
        encoding="utf-8",
    )
    assert parse_hint_segment_declaration(h / "ok.md") == ("05", "05-from-hints")


def test_merge_hint_declared_segments_inserts_sorted_id(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "z-decl.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: \"09\"\n    stem: 09-late\n---\n\n",
        encoding="utf-8",
    )
    (hints / "a-decl.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: \"02\"\n    stem: 02-mid\n---\n\n",
        encoding="utf-8",
    )
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
            "hints": "hints",
        },
        "segments": {"default": ["01", "03"], "all": ["01", "03"]},
        "segment_names": {"01": "01-a", "03": "03-c"},
        "discovery": {"auto_visual_map": False},
        "visual_map": {"01": {"type": "manim", "scene": "FooScene", "source": "x.mp4"}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    ch = merge_hint_declared_segments(cfg.raw, cfg)
    assert cfg.raw["segments"]["all"] == ["01", "02", "03", "09"]
    assert cfg.raw["segment_names"]["02"] == "02-mid"
    assert cfg.raw["segment_names"]["09"] == "09-late"
    assert ch


def test_merge_hint_declared_segments_disabled_in_discovery(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "decl.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: \"05\"\n    stem: 05-x\n---\n",
        encoding="utf-8",
    )
    raw = {
        "repo_root": ".",
        "dirs": {"hints": "hints"},
        "segments": {"default": ["01"], "all": ["01"]},
        "discovery": {"merge_hint_segments": False},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    assert merge_hint_declared_segments(cfg.raw, cfg) == []
    assert cfg.raw["segments"]["all"] == ["01"]


def test_merge_defaults_merge_hint_segments_false(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "decl.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: \"08\"\n    stem: 08-y\n---\n",
        encoding="utf-8",
    )
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
            "hints": "hints",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {"01": {"type": "manim", "scene": "S", "source": "S.mp4"}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    merge_defaults(cfg.raw, cfg, merge_hint_segments=False)
    assert cfg.raw["segments"]["all"] == ["01"]
    assert "08" not in cfg.raw.get("segment_names", {})


def test_collect_hint_segment_declarations_first_file_wins(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "a.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: \"04\"\n    stem: 04-first\n---\n",
        encoding="utf-8",
    )
    (hints / "b.md").write_text(
        "---\ndocgen:\n  segment:\n    create: true\n    id: \"04\"\n    stem: 04-second\n---\n",
        encoding="utf-8",
    )
    got = collect_hint_segment_declarations(hints)
    assert got == {"04": "04-first"}


def test_merge_hint_wiring_merges_visual_narration_manim(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "topic.md").write_text(
        "---\n"
        "docgen:\n"
        "  segment:\n"
        "    create: true\n"
        "    id: \"09\"\n"
        "    stem: 09-wired\n"
        "  wiring:\n"
        "    visual:\n"
        "      type: manim\n"
        "      scene: WiredScene\n"
        "      source: WiredScene.mp4\n"
        "    narration:\n"
        "      hints: [explain wiring]\n"
        "      context:\n"
        "        paths: [docs/foo.md]\n"
        "    manim_scene:\n"
        "      hints: [keep palette]\n"
        "      context:\n"
        "        paths: [hints/ext.md]\n"
        "---\n\n# body\n",
        encoding="utf-8",
    )
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
            "hints": "hints",
        },
        "segments": {"default": ["01", "09"], "all": ["01", "09"]},
        "segment_names": {"01": "01-a", "09": "09-wired"},
        "visual_map": {
            "01": {"type": "manim", "scene": "AScene", "source": "A.mp4"},
            "09": {"type": "manim", "scene": "WrongScene", "source": "Wrong.mp4"},
        },
        "narration_from_source": {"segments": {}},
        "manim_scene_generation": {
            "model": "gpt-4o",
            "segments": {"09": {"class_name": "WrongScene"}},
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    ch = merge_hint_wiring(cfg.raw, cfg)
    assert any("visual_map['09']" in x for x in ch)
    assert cfg.raw["visual_map"]["09"]["scene"] == "WiredScene"
    assert cfg.raw["narration_from_source"]["segments"]["09"]["hints"] == ["explain wiring"]
    merged = cfg.raw["manim_scene_generation"]["segments"]["09"]
    assert merged["class_name"] == "WiredScene"
    assert merged["hints"] == ["keep palette"]


def test_parse_hint_docgen_front_matter_returns_docgen_block(tmp_path: Path) -> None:
    h = tmp_path / "h.md"
    h.write_text("---\ndocgen:\n  segment:\n    create: true\n    id: 2\n    stem: 02-x\n---\n")
    doc = parse_hint_docgen_front_matter(h)
    assert doc is not None
    assert doc["segment"]["stem"] == "02-x"


def test_collect_hint_wirings_requires_segment_and_wiring(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "a.md").write_text(
        "---\ndocgen:\n  segment: {create: true, id: '01', stem: 01-x}\n---\n", encoding="utf-8"
    )
    assert collect_hint_wirings_by_segment(hints) == {}
    (hints / "b.md").write_text(
        "---\ndocgen:\n  segment: {create: true, id: '01', stem: 01-x}\n  wiring:\n    visual: {type: manim, scene: S, source: S.mp4}\n---\n",
        encoding="utf-8",
    )
    w = collect_hint_wirings_by_segment(hints)
    assert "01" in w and w["01"]["visual"]["scene"] == "S"


def test_merge_defaults_syncs_manim_scenes_list_in_segment_order(tmp_path: Path) -> None:
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
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


def test_merge_defaults_syncs_manim_scenes_from_visual_map_class_key(tmp_path: Path) -> None:
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
        },
        "segments": {"all": ["01", "02"], "default": ["01", "02"]},
        "discovery": {"auto_visual_map": False},
        "visual_map": {
            "01": {"type": "manim", "class": "OnlyClassScene"},
            "02": {"type": "manim", "scene": "ExplicitScene"},
        },
        "manim": {"scenes": []},
        "manim_scene_generation": {"segments": {}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    merge_defaults(raw, cfg)
    assert raw["manim"]["scenes"] == ["OnlyClassScene", "ExplicitScene"]
    assert raw["manim_scene_generation"]["segments"]["01"]["class_name"] == "OnlyClassScene"
    assert raw["manim_scene_generation"]["segments"]["02"]["class_name"] == "ExplicitScene"
