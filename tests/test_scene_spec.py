"""Unit tests for declarative scene YAML → Manim class compilation."""

from __future__ import annotations

from pathlib import Path

import pytest

from docgen.scene_spec import (
    SceneSpecError,
    align_wait_at_to_words,
    auto_paginate,
    compile_scene_class,
    layout_budget_violations,
    layout_stack_budget,
    load_scene_spec,
    validate_scene_spec,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "scene_fixture.scene.yaml"


def test_load_and_compile_fixture() -> None:
    raw = load_scene_spec(FIXTURE)
    validate_scene_spec(raw)
    merged = {**raw, "timing_key": "99-overview"}
    out = compile_scene_class(merged)
    assert "class TestDeclarativeScene(_TimedScene):" in out
    assert "def construct(self):" in out
    assert "timing = _load_timing('99-overview')" in out
    assert "title = Text('Test declarative', font_size=40, color=C_WHITE).to_edge(UP)" in out
    assert "_bx_0_0_0 = _box('Alpha', C_ORANGE, 5.0, 1.2, 28)" in out
    assert "_bx_0_1_0 = _box('Beta', C_BLUE, 3.5, 1.2, 24)" in out
    assert "_bx_0_1_1 = _box('Gamma', C_TEAL, 3.5, 1.2, 24)" in out
    assert "_row_0_0 = VGroup(_bx_0_0_0)" in out
    assert "_row_0_1 = VGroup(_bx_0_1_0, _bx_0_1_1).arrange(RIGHT, buff=0.35)" in out
    assert "_p0_stack = VGroup(_row_0_0, _row_0_1).arrange(DOWN, buff=0.35, center=True)" in out
    assert "_p0_stack.next_to(title, DOWN, buff=0.5)" in out
    assert "self.timed_play(FadeIn(_p0_stack[0]), run_time=1.0)" in out
    assert "self.timed_play(FadeIn(_p0_stack[1]), run_time=1.0)" in out


def test_multi_page_emits_transition_and_second_stack() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "PagedScene",
        "timing_key": "01-x",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "layout": {"page_transition_run_time": 0.5},
        "pages": [
            {
                "rows": [
                    {
                        "run_time": 0.5,
                        "boxes": [
                            {
                                "label": "P0",
                                "color": "C_GREEN",
                                "width": 3.0,
                                "height": 1.0,
                                "font_size": 20,
                            }
                        ],
                    }
                ],
            },
            {
                "rows": [
                    {
                        "run_time": 0.5,
                        "boxes": [
                            {
                                "label": "P1",
                                "color": "C_BLUE",
                                "width": 3.0,
                                "height": 1.0,
                                "font_size": 20,
                            }
                        ],
                    }
                ],
            },
        ],
    }
    out = compile_scene_class(spec)
    assert "_p0_stack" in out
    assert "_p1_stack" in out
    assert "self.timed_play(FadeOut(_p0_stack), run_time=0.5)" in out
    assert "FadeIn(_p1_stack[0])" in out


def test_validate_rejects_rows_and_pages_together() -> None:
    with pytest.raises(SceneSpecError, match="exactly one"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "rows": [
                    {
                        "run_time": 1.0,
                        "boxes": [
                            {
                                "label": "A",
                                "color": "C_GREEN",
                                "width": 2.0,
                                "height": 1.0,
                                "font_size": 18,
                            }
                        ],
                    }
                ],
                "pages": [],
            }
        )


def test_validate_rejects_bad_page_transition() -> None:
    with pytest.raises(SceneSpecError, match="page_transition"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "layout": {"page_transition": "wipe"},
                "rows": [
                    {
                        "run_time": 1.0,
                        "boxes": [
                            {
                                "label": "A",
                                "color": "C_GREEN",
                                "width": 2.0,
                                "height": 1.0,
                                "font_size": 18,
                            }
                        ],
                    }
                ],
            }
        )


def test_validate_rejects_empty_rows() -> None:
    with pytest.raises(SceneSpecError, match="non-empty list"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "rows": [],
            }
        )


def test_compile_wait_at_emits_absolute_wait() -> None:
    spec = {
        "segment_id": "05",
        "class_name": "AtScene",
        "timing_key": "05-x",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "wait_at": 12.5,
                "boxes": [
                    {
                        "label": "Late",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 1.0,
                        "font_size": 20,
                    }
                ],
            },
        ],
    }
    out = compile_scene_class(spec)
    assert "self.wait_until(12.5)" in out


def test_validate_rejects_wait_segment_and_wait_at_together() -> None:
    with pytest.raises(SceneSpecError, match="at most one"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "rows": [
                    {
                        "run_time": 1.0,
                        "wait_segment": 0,
                        "wait_at": 1.0,
                        "boxes": [
                            {
                                "label": "A",
                                "color": "C_GREEN",
                                "width": 2.0,
                                "height": 1.0,
                                "font_size": 18,
                            }
                        ],
                    }
                ],
            }
        )


def test_layout_stack_budget_decreases_with_larger_title_font() -> None:
    b_small = layout_stack_budget({"font_size": 32}, {"first_row_title_buff": 0.45})
    b_large = layout_stack_budget({"font_size": 40}, {"first_row_title_buff": 0.45})
    assert b_small > b_large


def test_layout_budget_violations_flags_tall_single_page() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "TallScene",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "layout": {"row_gap": 0.6, "first_row_title_buff": 0.5},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {"label": f"R{i}", "color": "C_GREEN", "width": 3.0, "height": 1.2, "font_size": 18},
                ],
            }
            for i in range(7)
        ],
    }
    issues = layout_budget_violations(spec)
    assert issues and any("exceeds frame budget" in msg for msg in issues)


def test_layout_budget_violations_accepts_split_pages() -> None:
    """Same box count as tall case but split — should pass vertical budget."""
    row = {
        "run_time": 1.0,
        "boxes": [
            {"label": "A", "color": "C_GREEN", "width": 3.0, "height": 0.78, "font_size": 17},
        ],
    }
    spec = {
        "segment_id": "1",
        "class_name": "PagedScene",
        "title": {"text": "T", "font_size": 32, "color": "C_WHITE"},
        "layout": {"row_gap": 0.36, "first_row_title_buff": 0.45},
        "pages": [
            {"rows": [row, row, row]},
            {"rows": [row, row, row], "transition": "fade"},
            {"rows": [row, row], "transition": "fade"},
        ],
    }
    assert layout_budget_violations(spec) == []


def test_layout_budget_violations_wide_row() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "WideScene",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "layout": {"column_gap": 0.8, "first_row_title_buff": 0.5, "row_gap": 0.6},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {"label": "A", "color": "C_GREEN", "width": 7.0, "height": 1.0, "font_size": 18},
                    {"label": "B", "color": "C_BLUE", "width": 7.0, "height": 1.0, "font_size": 18},
                ],
            },
        ],
    }
    issues = layout_budget_violations(spec)
    assert issues and any("safe width" in msg for msg in issues)


def test_compile_requires_timing_key() -> None:
    raw = load_scene_spec(FIXTURE)
    with pytest.raises(SceneSpecError, match="timing_key"):
        compile_scene_class(raw)


def _row(label: str, h: float = 1.0, w: float = 3.0) -> dict:
    return {
        "run_time": 1.0,
        "boxes": [
            {"label": label, "color": "C_GREEN", "width": w, "height": h, "font_size": 22},
        ],
    }


def test_auto_paginate_splits_rows_into_pages_within_budget() -> None:
    rows = [_row(f"R{i}") for i in range(8)]
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": rows,
    }
    out = auto_paginate(spec)
    assert "rows" not in out
    assert "pages" in out
    pages = out["pages"]
    assert len(pages) >= 2
    for pi, page in enumerate(pages):
        if pi == 0:
            assert "transition" not in page
        else:
            assert page["transition"] == "fade"
    assert layout_budget_violations(out) == []


def test_auto_paginate_leaves_fitting_single_page_untouched() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [_row("A"), _row("B"), _row("C")],
    }
    out = auto_paginate(spec)
    assert "rows" in out
    assert "pages" not in out


def test_auto_paginate_preserves_explicit_pages_transitions() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "pages": [
            {"rows": [_row("A"), _row("B")]},
            {"rows": [_row("C")], "transition": "none"},
        ],
    }
    out = auto_paginate(spec)
    pages = out["pages"]
    assert len(pages) == 2
    assert "transition" not in pages[0]
    assert pages[1]["transition"] == "none"


def test_align_wait_at_to_words_picks_first_mention_per_label() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [_row("Whisper"), _row("Manim"), _row("Compose")],
    }
    words = [
        {"word": "the", "start": 0.0, "end": 0.3},
        {"word": "Whisper", "start": 1.5, "end": 1.9},
        {"word": "tool", "start": 2.0, "end": 2.4},
        {"word": "Manim", "start": 3.5, "end": 3.9},
        {"word": "and", "start": 4.0, "end": 4.2},
        {"word": "Compose", "start": 5.5, "end": 5.9},
    ]
    out = align_wait_at_to_words(spec, words)
    assert out["rows"][0]["wait_at"] == 1.5
    assert out["rows"][1]["wait_at"] == 3.5
    assert out["rows"][2]["wait_at"] == 5.5


def test_align_wait_at_handles_multi_word_labels_and_advances_cursor() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [_row("Demo Function"), _row("Function")],
    }
    words = [
        {"word": "the", "start": 0.0, "end": 0.3},
        {"word": "demo", "start": 1.0, "end": 1.4},
        {"word": "function", "start": 1.5, "end": 1.9},
        {"word": "called", "start": 2.0, "end": 2.4},
        {"word": "function", "start": 4.0, "end": 4.4},
    ]
    out = align_wait_at_to_words(spec, words)
    assert out["rows"][0]["wait_at"] == 1.0
    assert out["rows"][1]["wait_at"] == 4.0


def test_align_wait_at_matches_label_to_inflected_word() -> None:
    """Engine-side stem matcher: ``Trace`` aligns to spoken ``tracing`` without YAML edits."""
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [_row("Trace"), _row("Compose")],
    }
    words = [
        {"word": "the", "start": 0.0, "end": 0.3},
        {"word": "tracing", "start": 1.5, "end": 2.0},
        {"word": "step", "start": 2.1, "end": 2.4},
        {"word": "composing", "start": 5.5, "end": 6.0},
    ]
    out = align_wait_at_to_words(spec, words)
    assert out["rows"][0]["wait_at"] == 1.5
    assert out["rows"][1]["wait_at"] == 5.5


def test_align_wait_at_does_not_stem_match_short_tokens() -> None:
    """Short product names like ``TTS`` keep strict equality so they don't snag random tokens."""
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [_row("TTS")],
    }
    words = [
        {"word": "the", "start": 0.0, "end": 0.3},
        {"word": "tts", "start": 1.0, "end": 1.4},
    ]
    out = align_wait_at_to_words(spec, words)
    assert out["rows"][0]["wait_at"] == 1.0


def test_align_wait_at_does_not_overwrite_existing_unless_asked() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {**_row("Whisper"), "wait_at": 99.0},
        ],
    }
    words = [{"word": "Whisper", "start": 1.5, "end": 1.9}]
    out = align_wait_at_to_words(spec, words)
    assert out["rows"][0]["wait_at"] == 99.0
    out2 = align_wait_at_to_words(spec, words, overwrite=True)
    assert out2["rows"][0]["wait_at"] == 1.5
