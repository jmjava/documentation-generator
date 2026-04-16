"""Tests for docgen.scene_gen — auto-generated Manim scenes from narration."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from docgen.config import Config
from docgen.scene_gen import (
    SceneGenerator,
    SegmentScene,
    VisualBeat,
    assign_timing,
    generate_scene_code,
    load_timing,
    parse_narration,
)


# ── parse_narration ───────────────────────────────────────────────────


class TestParseNarration:
    def test_extracts_headings(self):
        beats = parse_narration("# Welcome\nSome text.\n## Details\n")
        titles = [b for b in beats if b.kind == "title"]
        assert len(titles) == 2
        assert titles[0].text == "Welcome"
        assert titles[1].text == "Details"

    def test_extracts_bullets(self):
        text = "- First item\n- Second item\n- Third item\n"
        beats = parse_narration(text)
        bullet_beats = [b for b in beats if b.kind == "bullets"]
        assert len(bullet_beats) == 1
        assert bullet_beats[0].items == ["First item", "Second item", "Third item"]

    def test_extracts_numbered_list(self):
        text = "1. Alpha\n2. Beta\n3. Gamma\n"
        beats = parse_narration(text)
        bullet_beats = [b for b in beats if b.kind == "bullets"]
        assert len(bullet_beats) == 1
        assert bullet_beats[0].items == ["Alpha", "Beta", "Gamma"]

    def test_extracts_plain_text(self):
        text = "This is a spoken paragraph about Tekton pipelines."
        beats = parse_narration(text)
        assert len(beats) == 1
        assert beats[0].kind == "text"
        assert "Tekton" in beats[0].text

    def test_strips_markdown_inline(self):
        text = "This is **bold** and `code` and [link](http://x.com)."
        beats = parse_narration(text)
        assert beats[0].text == "This is bold and code and link."

    def test_horizontal_rule_becomes_transition(self):
        text = "Before\n---\nAfter"
        beats = parse_narration(text)
        kinds = [b.kind for b in beats]
        assert "transition" in kinds

    def test_skips_metadata_lines(self):
        text = "target duration: 2 minutes\n# Real Heading\n"
        beats = parse_narration(text)
        assert len(beats) == 1
        assert beats[0].kind == "title"

    def test_skips_stage_directions(self):
        text = "*(pause)*\n# Title\n"
        beats = parse_narration(text)
        assert len(beats) == 1
        assert beats[0].kind == "title"

    def test_empty_input(self):
        assert parse_narration("") == []
        assert parse_narration("\n\n\n") == []

    def test_mixed_content(self):
        text = "# Intro\nSome narration.\n- Point A\n- Point B\n---\n# Conclusion\n"
        beats = parse_narration(text)
        kinds = [b.kind for b in beats]
        assert kinds == ["title", "text", "bullets", "transition", "title"]


# ── assign_timing ─────────────────────────────────────────────────────


class TestAssignTiming:
    def test_distributes_time_evenly(self):
        beats = [
            VisualBeat(kind="title", text="A"),
            VisualBeat(kind="text", text="B"),
        ]
        assign_timing(beats, 20.0)
        assert beats[0].at_sec == 0.0
        assert beats[1].at_sec > beats[0].at_sec

    def test_skips_transitions(self):
        beats = [
            VisualBeat(kind="title", text="A"),
            VisualBeat(kind="transition"),
            VisualBeat(kind="text", text="B"),
        ]
        assign_timing(beats, 20.0)
        assert beats[1].kind == "transition"
        assert beats[2].at_sec > beats[0].at_sec

    def test_empty_beats(self):
        beats: list[VisualBeat] = []
        assign_timing(beats, 10.0)

    def test_minimum_duration(self):
        beats = [VisualBeat(kind="text", text=f"Item {i}") for i in range(20)]
        assign_timing(beats, 30.0)
        for b in beats:
            assert b.duration_sec >= 3.0


# ── generate_scene_code ───────────────────────────────────────────────


class TestGenerateSceneCode:
    def test_generates_valid_python(self):
        scene = SegmentScene(
            segment_id="01",
            scene_name="Scene01",
            beats=[VisualBeat(kind="title", text="Hello World", at_sec=0.0, duration_sec=5.0)],
            total_duration_sec=10.0,
            font="Liberation Sans",
        )
        code = generate_scene_code(scene)
        assert "class Scene01(Scene):" in code
        assert "from manim import *" in code
        assert "Liberation Sans" in code
        assert "Hello World" in code
        compile(code, "<test>", "exec")

    def test_generates_bullet_scene(self):
        scene = SegmentScene(
            segment_id="02",
            scene_name="Scene02",
            beats=[VisualBeat(
                kind="bullets",
                items=["First", "Second", "Third"],
                at_sec=0.0,
                duration_sec=8.0,
            )],
            total_duration_sec=10.0,
        )
        code = generate_scene_code(scene)
        assert "bullet_group" in code
        assert "First" in code
        assert "arrange(DOWN" in code
        compile(code, "<test>", "exec")

    def test_empty_beats_generates_wait(self):
        scene = SegmentScene(segment_id="03", scene_name="Scene03", beats=[])
        code = generate_scene_code(scene)
        assert "self.wait(2)" in code
        compile(code, "<test>", "exec")

    def test_escapes_quotes(self):
        scene = SegmentScene(
            segment_id="04",
            scene_name="Scene04",
            beats=[VisualBeat(kind="text", text='He said "hello"', at_sec=0.0, duration_sec=5.0)],
        )
        code = generate_scene_code(scene)
        compile(code, "<test>", "exec")

    def test_replaces_unsafe_unicode(self):
        scene = SegmentScene(
            segment_id="05",
            scene_name="Scene05",
            beats=[VisualBeat(kind="text", text="arrow \u2192 here", at_sec=0.0, duration_sec=5.0)],
        )
        code = generate_scene_code(scene)
        assert "\u2192" not in code
        assert "->" in code

    def test_uses_relative_layout(self):
        """Generated code should use arrange/center, not absolute coordinates."""
        scene = SegmentScene(
            segment_id="06",
            scene_name="Scene06",
            beats=[
                VisualBeat(kind="title", text="Title", at_sec=0.0, duration_sec=3.0),
                VisualBeat(kind="bullets", items=["A", "B"], at_sec=4.0, duration_sec=5.0),
            ],
        )
        code = generate_scene_code(scene)
        assert "to_edge" in code or "center" in code
        assert "arrange(DOWN" in code
        assert "move_to" not in code

    def test_never_uses_bold(self):
        """Generated scenes must not use weight=BOLD."""
        scene = SegmentScene(
            segment_id="07",
            scene_name="Scene07",
            beats=[
                VisualBeat(kind="title", text="Title", at_sec=0.0, duration_sec=3.0),
                VisualBeat(kind="bullets", items=["A", "B"], at_sec=4.0, duration_sec=5.0),
                VisualBeat(kind="text", text="Body", at_sec=10.0, duration_sec=3.0),
            ],
        )
        code = generate_scene_code(scene)
        assert "BOLD" not in code
        assert "weight" not in code


# ── load_timing ──────────────────────────────────────────────────────


class TestLoadTiming:
    def test_loads_duration_from_timing_json(self, tmp_path):
        cfg = _make_config(tmp_path)
        timing = {"01-overview": {"duration": 95.5, "segments": []}}
        (tmp_path / "animations" / "timing.json").write_text(
            json.dumps(timing), encoding="utf-8"
        )
        result = load_timing(cfg, "01")
        assert result == 95.5

    def test_returns_none_when_missing(self, tmp_path):
        cfg = _make_config(tmp_path)
        assert load_timing(cfg, "01") is None

    def test_uses_segment_end_as_fallback(self, tmp_path):
        cfg = _make_config(tmp_path)
        timing = {
            "01-overview": {
                "segments": [
                    {"start": 0.0, "end": 45.0, "text": "..."},
                    {"start": 45.0, "end": 90.0, "text": "..."},
                ]
            }
        }
        (tmp_path / "animations" / "timing.json").write_text(
            json.dumps(timing), encoding="utf-8"
        )
        result = load_timing(cfg, "01")
        assert result == 90.0


# ── SceneGenerator integration ────────────────────────────────────────


class TestSceneGenerator:
    def test_generates_scene_file(self, tmp_path):
        cfg = _make_config(tmp_path)
        narr = tmp_path / "narration" / "01-overview.md"
        narr.write_text("# Welcome\nThis is the overview.\n- Feature A\n- Feature B\n")
        gen = SceneGenerator(cfg)
        created = gen.generate()
        assert len(created) == 1
        scene_file = Path(created[0])
        assert scene_file.exists()
        code = scene_file.read_text()
        assert "class DocgenOverviewScene(Scene):" in code
        compile(code, "<test>", "exec")

    def test_dry_run_does_not_write(self, tmp_path):
        cfg = _make_config(tmp_path)
        narr = tmp_path / "narration" / "01-overview.md"
        narr.write_text("# Hello\nWorld\n")
        gen = SceneGenerator(cfg)
        created = gen.generate(dry_run=True)
        assert created == []
        assert not (tmp_path / "animations" / "scene_01.py").exists()

    def test_skips_existing_without_force(self, tmp_path):
        cfg = _make_config(tmp_path)
        narr = tmp_path / "narration" / "01-overview.md"
        narr.write_text("# Hello\nWorld\n")
        scene = tmp_path / "animations" / "scene_01.py"
        scene.write_text("existing content")
        gen = SceneGenerator(cfg)
        created = gen.generate()
        assert created == []
        assert scene.read_text() == "existing content"

    def test_force_overwrites(self, tmp_path):
        cfg = _make_config(tmp_path)
        narr = tmp_path / "narration" / "01-overview.md"
        narr.write_text("# Hello\nWorld\n")
        scene = tmp_path / "animations" / "scene_01.py"
        scene.write_text("existing content")
        gen = SceneGenerator(cfg)
        created = gen.generate(force=True)
        assert len(created) == 1
        assert "existing content" not in scene.read_text()

    def test_skips_non_manim_segments(self, tmp_path):
        cfg_data = {
            "segments": {"default": ["01"], "all": ["01"]},
            "segment_names": {"01": "01-overview"},
            "visual_map": {"01": {"type": "vhs", "source": "01.mp4"}},
        }
        (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg_data), encoding="utf-8")
        for d in ("narration", "audio", "animations", "terminal", "recordings"):
            (tmp_path / d).mkdir(exist_ok=True)
        (tmp_path / "narration" / "01-overview.md").write_text("# Hello\n")
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        gen = SceneGenerator(cfg)
        created = gen.generate()
        assert created == []


# ── Helpers ───────────────────────────────────────────────────────────


def _make_config(tmp_path: Path) -> Config:
    cfg = {
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-overview"},
        "visual_map": {"01": {"type": "manim", "scene": "DocgenOverviewScene", "source": "DocgenOverviewScene.mp4"}},
        "manim": {"font": "Liberation Sans"},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    for d in ("narration", "audio", "animations", "terminal", "recordings"):
        (tmp_path / d).mkdir(exist_ok=True)
    return Config.from_yaml(tmp_path / "docgen.yaml")
