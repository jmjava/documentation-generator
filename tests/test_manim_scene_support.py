"""Unit tests for ``docgen.manim_scene_support``.

Covers settings merge, class-name derivation, marker-block injection (idempotent
regeneration), bootstrap path for fresh ``scenes.py`` files, and
:class:`lint_generated_block`. The OpenAI path lives in ``scene_spec_generate``;
no ``OPENAI_API_KEY`` is required here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.manim_scene_support import (
    BOOTSTRAP_HEADER,
    DEFAULT_MODEL,
    REQUIRED_HELPERS,
    SceneGenerationError,
    append_audio_tail_to_class_body,
    build_timing_enrichment_for_prompt,
    derive_class_name,
    ensure_scenes_bootstrap,
    extract_reference_classes,
    inject_or_replace,
    lint_generated_block,
    merged_scene_generation_settings,
    sync_audio_tail_waits_in_scenes,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


def _write_cfg(tmp_path: Path, overrides: dict | None = None) -> Config:
    cfg: dict = {
        "dirs": {
            "narration": "narration",
            "animations": "animations",
            "audio": "audio",
            "recordings": "recordings",
        },
        "segments": {"default": ["08"], "all": ["08"]},
        "segment_names": {"08": "08-extras"},
        "visual_map": {"08": {"type": "manim", "scene": "ExtrasScene", "source": "ExtrasScene.mp4"}},
    }
    if overrides:
        cfg.update(overrides)
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


# ── Settings merge ─────────────────────────────────────────────────────────


def test_settings_default_when_yaml_block_missing(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path)
    s = merged_scene_generation_settings(cfg, "08")
    assert s.model == DEFAULT_MODEL
    assert s.hints == []
    assert s.context_paths == []
    assert s.class_name is None


def test_build_timing_enrichment_segments_only_suggests_wait_segment(
    tmp_path: Path,
) -> None:
    cfg = _write_cfg(
        tmp_path,
        {
            "manim_scene_generation": {
                "segments": {
                    "08": {"visual_beats": 3, "class_name": "ExtrasScene"},
                },
            },
        },
    )
    segs = [
        {"start": 0.0, "end": 1.0, "text": "alpha"},
        {"start": 1.0, "end": 2.0, "text": "bravo"},
        {"start": 2.0, "end": 3.0, "text": "charlie"},
        {"start": 3.0, "end": 4.0, "text": "delta"},
    ]
    out = build_timing_enrichment_for_prompt(cfg, "08", "08-extras", segs)
    assert "whisper_index" in out
    assert "wait_segment" in out
    assert "_DOCGEN_PACE_SEG" not in out
    assert "pace_to_beat" not in out
    assert "| 0 | 0 |" in out
    assert "| 1 | 2 |" in out
    assert "| 2 | 3 |" in out


def test_build_timing_enrichment_words_primary_and_no_pace_tuple(
    tmp_path: Path,
) -> None:
    cfg = _write_cfg(
        tmp_path,
        {
            "manim_scene_generation": {
                "segments": {"08": {"class_name": "ExtrasScene"}},
            },
        },
    )
    anim = tmp_path / "animations"
    anim.mkdir(parents=True, exist_ok=True)
    timing = {
        "08-extras": {
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
            "words": [
                {"start": 0.0, "end": 0.5, "word": "hello"},
                {"start": 0.5, "end": 1.0, "word": "world"},
            ],
        }
    }
    (anim / "timing.json").write_text(json.dumps(timing), encoding="utf-8")
    segs = timing["08-extras"]["segments"]
    out = build_timing_enrichment_for_prompt(cfg, "08", "08-extras", segs)
    assert "WORD TIMING" in out
    assert "wait_word" in out
    assert '"word_index": 0' in out
    assert "_DOCGEN_PACE_SEG" not in out
    assert "pace_to_beat" not in out


def test_settings_root_and_segment_overrides_merge(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path,
        {
            "manim_scene_generation": {
                "model": "gpt-4o-mini",
                "temperature": 0.2,
                "hints": ["root-hint"],
                "context": {"paths": ["src/docgen/cli.py"], "globs": []},
                "segments": {
                    "08": {
                        "class_name": "ExtrasScene",
                        "hints": ["seg-hint-1", "seg-hint-2"],
                        "context": {"paths": ["src/docgen/compose.py"]},
                    }
                },
            }
        },
    )
    s = merged_scene_generation_settings(cfg, "08")
    assert s.model == "gpt-4o-mini"
    assert s.temperature == pytest.approx(0.2)
    assert s.hints == ["root-hint", "seg-hint-1", "seg-hint-2"]
    assert s.context_paths == ["src/docgen/cli.py", "src/docgen/compose.py"]
    assert s.class_name == "ExtrasScene"


# ── Class-name derivation ──────────────────────────────────────────────────


def test_derive_class_name_uses_override_when_provided() -> None:
    assert derive_class_name("08", "08-extras-overview", "MyScene") == "MyScene"


def test_derive_class_name_strips_leading_id_and_camelizes() -> None:
    assert derive_class_name("08", "08-extras-overview", None) == "ExtrasOverviewScene"


def test_derive_class_name_handles_underscore_and_spaces() -> None:
    assert derive_class_name("12", "12_my segment", None) == "MySegmentScene"


def test_derive_class_name_falls_back_to_segment_id_when_name_empty() -> None:
    assert derive_class_name("08", "", None) == "Segment08Scene"


# ── Audio-length tail (Manim duration vs TTS) ───────────────────────────


def test_append_audio_tail_inserts_wait_before_mass_fadeout() -> None:
    src = (
        "class X(_TimedScene):\n"
        "    def construct(self):\n"
        "        self.timed_play(Write(Text('a', font_size=24)), run_time=1.0)\n"
        "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
    )
    out = append_audio_tail_to_class_body(src, "01-overview")
    assert "audio-length tail" in out
    assert "_load_timing('01-overview')" in out
    assert "wait_until" in out
    assert out.index("wait_until") < out.index("FadeOut")


def test_append_audio_tail_idempotent() -> None:
    src = (
        "class X(_TimedScene):\n"
        "    def construct(self):\n"
        "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
    )
    once = append_audio_tail_to_class_body(src, "01-overview")
    twice = append_audio_tail_to_class_body(once, "zz-never")
    assert once == twice


def test_append_audio_tail_comment_only_when_llm_already_waited_for_end() -> None:
    src = (
        "class X(_TimedScene):\n"
        "    def construct(self):\n"
        "        _segs = _load_timing('01-intro')\n"
        "        if _segs:\n"
        "            self.wait_until(\n"
        "                max(float(s.get(\"end\", 0.0)) for s in _segs)\n"
        "            )\n"
        "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
    )
    out = append_audio_tail_to_class_body(src, "01-intro")
    assert out.count("self.wait_until(") == 1
    assert "_docgen_segs" not in out
    assert "audio-length tail" in out
    assert out.index("audio-length tail") < out.index("FadeOut")


def test_sync_audio_tail_waits_patches_marked_block(tmp_path: Path) -> None:
    import json

    (tmp_path / "animations").mkdir(parents=True)
    scenes = """# ── BEGIN GENERATED SCENE: 01 (OverviewScene) ──
class OverviewScene(_TimedScene):
    def construct(self):
        self.timed_play(Write(Text("x", font_size=24)), run_time=1.0)
        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)
# ── END GENERATED SCENE: 01 ──
"""
    (tmp_path / "animations" / "scenes.py").write_text(scenes, encoding="utf-8")
    timing = {"01-test": {"segments": [{"start": 0.0, "end": 99.5, "text": "x"}]}}
    (tmp_path / "animations" / "timing.json").write_text(
        json.dumps(timing) + "\n", encoding="utf-8"
    )
    raw = {
        "dirs": {
            "narration": "n",
            "audio": "a",
            "animations": "animations",
            "recordings": "r",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-test"},
        "visual_map": {"01": {"type": "manim", "scene": "OverviewScene", "source": "OverviewScene.mp4"}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    msgs = sync_audio_tail_waits_in_scenes(cfg)
    assert msgs and "segment 01" in msgs[0]
    updated = (tmp_path / "animations" / "scenes.py").read_text(encoding="utf-8")
    assert "wait_until" in updated
    assert sync_audio_tail_waits_in_scenes(cfg) == []


_GOOD_CLASS = (
    "class DemoFunctionScene(_TimedScene):\n"
    "    def construct(self):\n"
    "        self.camera.background_color = C_BG\n"
    "        title = Text('demo', font_size=42, color=C_ACCENT)\n"
    "        self.timed_play(Write(title), run_time=1.0)\n"
    "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
    "        self.timed_wait(0.5)\n"
)


# ── Marker injection (idempotent regeneration) ─────────────────────────────


def test_inject_appends_when_marker_absent() -> None:
    base = BOOTSTRAP_HEADER
    result = inject_or_replace(base, "08", "DemoFunctionScene", _GOOD_CLASS)
    assert "BEGIN GENERATED SCENE: 08 (DemoFunctionScene)" in result
    assert "END GENERATED SCENE: 08" in result
    assert _GOOD_CLASS.strip() in result
    # Bootstrap is preserved verbatim:
    assert result.startswith(BOOTSTRAP_HEADER)


def test_inject_replaces_existing_block_idempotently() -> None:
    base = BOOTSTRAP_HEADER
    once = inject_or_replace(base, "08", "DemoFunctionScene", _GOOD_CLASS)
    new_class = _GOOD_CLASS.replace("'demo'", "'demo v2'")
    twice = inject_or_replace(once, "08", "DemoFunctionScene", new_class)

    # Only ONE generated block remains:
    assert twice.count("BEGIN GENERATED SCENE: 08 (DemoFunctionScene)") == 1
    assert twice.count("END GENERATED SCENE: 08") == 1
    assert "'demo v2'" in twice
    assert "'demo'" not in twice.replace("'demo v2'", "")
    # And it's still a parsable Python file:
    import ast
    ast.parse(twice)


def test_inject_replaces_block_when_class_name_changes_keeping_seg_id() -> None:
    base = BOOTSTRAP_HEADER
    once = inject_or_replace(base, "08", "OldName", _GOOD_CLASS.replace("DemoFunctionScene", "OldName"))
    twice = inject_or_replace(once, "08", "NewName", _GOOD_CLASS.replace("DemoFunctionScene", "NewName"))
    assert "OldName" not in twice
    assert "BEGIN GENERATED SCENE: 08 (NewName)" in twice
    assert twice.count("END GENERATED SCENE: 08") == 1


# ── Bootstrap ──────────────────────────────────────────────────────────────


def test_ensure_bootstrap_writes_template_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    ensure_scenes_bootstrap(p)
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    for helper in REQUIRED_HELPERS:
        assert helper in text


def test_ensure_bootstrap_leaves_existing_helpers_alone(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    p.write_text(BOOTSTRAP_HEADER, encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    ensure_scenes_bootstrap(p)
    assert p.read_text(encoding="utf-8") == before


def test_ensure_bootstrap_refuses_partial_helpers(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    p.write_text("def _box():\n    return None\n", encoding="utf-8")
    with pytest.raises(SceneGenerationError, match="missing required helpers"):
        ensure_scenes_bootstrap(p)


def test_ensure_bootstrap_refuses_unparsable_file(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    p.write_text("def broken(", encoding="utf-8")
    with pytest.raises(SceneGenerationError, match="did not parse"):
        ensure_scenes_bootstrap(p)


# ── Reference scenes extraction ────────────────────────────────────────────


def test_extract_reference_classes_returns_only_public_classes() -> None:
    text = (
        BOOTSTRAP_HEADER
        + "\nclass DocgenOverviewScene(_TimedScene):\n    def construct(self):\n        pass\n"
        + "\nclass _Helper(_TimedScene):\n    pass\n"
    )
    out = extract_reference_classes(text)
    assert "DocgenOverviewScene" in out
    assert "_Helper" not in out
    # Bootstrap helpers are not echoed back:
    assert "C_BG = " not in out
    assert "def _box" not in out


def test_extract_reference_classes_returns_empty_for_unparsable() -> None:
    assert extract_reference_classes("def broken(") == ""


def test_extract_reference_classes_handles_empty_text() -> None:
    assert extract_reference_classes("") == ""


# ── Pre-write lint (font_size, weight=BOLD, unsafe unicode) ────────────────


def test_lint_flags_title_down_row_collision_pattern() -> None:
    bad = (
        "class X(_TimedScene):\n"
        "    def construct(self):\n"
        "        a = _box('a', C_GREEN, 1, 1).shift(LEFT * 3)\n"
        "        b = _box('b', C_BLUE, 1, 1).shift(RIGHT * 3)\n"
        "        c = _box('c', C_ORANGE, 2, 1).next_to(title, DOWN, buff=1)\n"
    )
    issues = lint_generated_block(bad, min_font_size=14, unsafe_unicode=[])
    assert any("layout:" in i and "shift(LEFT" in i for i in issues)


def test_lint_passes_vgroup_row_without_title_down_collision() -> None:
    issues = lint_generated_block(_GOOD_CLASS, min_font_size=14, unsafe_unicode=["\u2192"])
    assert issues == []


def test_lint_flags_small_font_size() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        Text('hi', font_size=12, color=C_RED)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("font_size=12" in i for i in issues)


def test_lint_flags_weight_bold() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        Text('hi', font_size=20, color=C_ACCENT, weight=BOLD)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("weight=BOLD" in i for i in issues)


def test_lint_flags_unsafe_unicode_in_string() -> None:
    # Use real U+2192 in the simulated source; `'\\u2192'` in a .py file is
    # six ASCII chars, not the arrow glyph, so the unicode scan would miss it.
    arrow = chr(0x2192)
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        f"        Text('left {arrow} right', font_size=20, color=C_WHITE)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=["\u2192"])
    assert any("U+2192" in i for i in issues)


def test_lint_flags_unsafe_unicode_in_comment() -> None:
    em_dash = chr(0x2014)
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        f"        # the manifest {em_dash} plus a label\n"
        "        Text('ok', font_size=20, color=C_WHITE)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=["\u2014"])
    assert any("U+2014" in i for i in issues)


def test_lint_flags_set_opacity_zero_then_fadein_anti_pattern() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        chip = _box('x', C_GREEN, 1, 1)\n"
        "        chip.set_opacity(0)\n"
        "        self.timed_play(FadeIn(chip), run_time=0.5)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("set_opacity(0)" in i and "FadeIn" in i for i in issues)


def test_lint_flags_low_buff_next_to_title_down() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        title = Text('t', font_size=42, color=C_WHITE)\n"
        "        row = VGroup().arrange(RIGHT, buff=0.4)\n"
        "        row.next_to(title, DOWN, buff=0.2)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("buff=0.2" in i and "title" in i for i in issues)


def test_lint_passes_safe_buff_next_to_title_down() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        title = Text('t', font_size=42, color=C_WHITE)\n"
        "        row = VGroup().arrange(RIGHT, buff=0.4)\n"
        "        row.next_to(title, DOWN, buff=0.5)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert not any("title" in i and "overlap" in i.lower() for i in issues)


def test_lint_flags_animate_shift_up_on_placed_content() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        statuses = VGroup()\n"
        "        self.timed_play(statuses.animate.shift(UP * 0.75), run_time=1.0)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("UP * 0.75" in i and "title band" in i for i in issues)


def test_lint_passes_to_edge_down_for_new_bottom_content() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        tracks = VGroup().arrange(RIGHT).to_edge(DOWN, buff=0.5)\n"
        "        self.timed_play(FadeIn(tracks), run_time=1.0)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert not any("title band" in i for i in issues)


def test_lint_passes_paced_reveal_helper_pattern() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        chips = [_box('x', C_GREEN, 1, 1)]\n"
        "        _segs = _load_timing('01-x')\n"
        "        self.paced_reveal(_segs, chips, (0,))\n"
        "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert not any("set_opacity(0)" in i for i in issues)


def test_lint_returns_partial_issues_when_unparsable() -> None:
    """Syntax-broken code still surfaces unicode line-scan issues; AST checks bail."""
    arrow = chr(0x2192)
    code = f"Text('x {arrow} y', font_size=12,\n# unbalanced"
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=["\u2192"])
    assert any("U+2192" in i for i in issues)
