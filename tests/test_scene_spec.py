"""Unit tests for declarative scene YAML → Manim class compilation."""

from __future__ import annotations

from pathlib import Path

import pytest

from docgen.scene_spec import (
    SceneSpecError,
    auto_paginate,
    coerce_legacy_wait_at_to_whisper_rows,
    compile_scene_class,
    layout_budget_violations,
    layout_stack_budget,
    load_scene_spec,
    segment_index_for_whisper_time,
    sync_row_labels_to_whisper_words,
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
    assert "timing_words = _load_timing_words('99-overview')" in out
    assert "_docgen_segs = _load_timing('99-overview')" in out
    assert "title = Text('Test declarative', font_size=40, color=C_WHITE).to_edge(UP)" in out
    assert "_bx_0_0_0 = _box('Alpha', C_ORANGE, 5.0, 1.2, 28)" in out
    assert "_bx_0_1_0 = _box('Beta', C_BLUE, 3.5, 1.2, 24)" in out
    assert "_bx_0_1_1 = _box('Gamma', C_TEAL, 3.5, 1.2, 24)" in out
    assert "_row_0_0 = VGroup(_bx_0_0_0)" in out
    assert "_row_0_1 = VGroup(_bx_0_1_0, _bx_0_1_1).arrange(RIGHT, buff=0.35)" in out
    assert "_p0_stack = VGroup(_row_0_0, _row_0_1).arrange(DOWN, buff=0.35, center=True)" in out
    assert "_p0_stack.next_to(title, DOWN, buff=0.5)" in out
    assert "self.timed_play(FadeIn(_bx_0_0_0), run_time=1.0)" in out
    assert "self.timed_play(FadeIn(_bx_0_1_0), run_time=1.0)" in out
    assert "self.timed_play(FadeIn(_bx_0_1_1), run_time=1.0)" in out


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
    assert "timing_words = _load_timing_words('01-x')" in out
    assert "_p1_stack" in out
    assert "self.timed_play(FadeOut(_p0_stack), run_time=0.5)" in out
    assert "FadeIn(_bx_1_0_0)" in out


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


def test_compile_rejects_wait_at() -> None:
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
    with pytest.raises(SceneSpecError, match="wait_at"):
        validate_scene_spec(spec)


def test_coerce_legacy_wait_at_prefers_wait_word_when_words_present() -> None:
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
    words = [
        {"word": "early", "start": 0.0, "end": 1.0},
        {"word": "late", "start": 10.0, "end": 11.0},
    ]
    segments = [
        {"start": 0.0, "end": 15.0},
        {"start": 15.0, "end": 30.0},
    ]
    merged = coerce_legacy_wait_at_to_whisper_rows(spec, words, segments)
    validate_scene_spec(merged)
    assert merged["rows"][0]["boxes"][0]["wait_word"] == 1
    assert merged["rows"][0].get("wait_word") is None
    out = compile_scene_class(merged)
    assert "self.wait_until_word(timing_words, 1)" in out
    assert "timing_words = _load_timing_words('05-x')" in out
    assert "        timing = _load_timing(" not in out


def test_coerce_legacy_wait_at_drops_when_no_words_even_if_segments_exist() -> None:
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
    segments = [
        {"start": 0.0, "end": 15.0},
        {"start": 15.0, "end": 30.0},
    ]
    merged = coerce_legacy_wait_at_to_whisper_rows(spec, [], segments)
    validate_scene_spec(merged)
    assert "wait_segment" not in merged["rows"][0]
    assert merged["rows"][0].get("wait_word") is None
    assert "wait_word" not in merged["rows"][0]["boxes"][0]
    assert "wait_at" not in merged["rows"][0]
    out = compile_scene_class(merged)
    assert "wait_until_word" not in out


def test_compile_rejects_wait_segment() -> None:
    spec = {
        "segment_id": "03",
        "class_name": "SegScene",
        "timing_key": "03-x",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "wait_segment": 0,
                "boxes": [
                    {
                        "label": "A",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 1.0,
                        "font_size": 20,
                    }
                ],
            },
        ],
    }
    with pytest.raises(SceneSpecError, match="wait_segment is not supported"):
        compile_scene_class(spec)


def test_segment_index_for_whisper_time_brackets() -> None:
    segs = [{"start": 0.0, "end": 10.0}, {"start": 10.0, "end": 20.0}]
    assert segment_index_for_whisper_time(segs, 0.0) == 0
    assert segment_index_for_whisper_time(segs, 12.5) == 1


def test_compile_wait_word_emits_wait_until_word() -> None:
    spec = {
        "segment_id": "03",
        "class_name": "WordScene",
        "timing_key": "03-x",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {
                        "label": "A",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 1.0,
                        "font_size": 20,
                        "wait_word": 7,
                    }
                ],
            },
        ],
    }
    out = compile_scene_class(spec)
    assert "self.wait_until_word(timing_words, 7)" in out
    assert "FadeIn(_bx_0_0_0)" in out
    assert "timing_words = _load_timing_words('03-x')" in out


def test_validate_rejects_wait_at_key() -> None:
    with pytest.raises(SceneSpecError, match="wait_at"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "rows": [
                    {
                        "run_time": 1.0,
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


def test_validate_rejects_wait_word_and_wait_segment_together() -> None:
    with pytest.raises(SceneSpecError, match="at most one"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "rows": [
                    {
                        "run_time": 1.0,
                        "wait_word": 0,
                        "wait_segment": 1,
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


def test_sync_row_labels_sets_wait_word_indices() -> None:
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
    out = sync_row_labels_to_whisper_words(spec, words)
    assert [out["rows"][i]["boxes"][0].get("wait_word") for i in range(3)] == [1, 3, 5]


def test_sync_row_labels_assigns_each_box_in_a_row() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {"label": "Alpha", "color": "C_GREEN", "width": 2.0, "height": 1.0, "font_size": 18},
                    {"label": "Beta", "color": "C_BLUE", "width": 2.0, "height": 1.0, "font_size": 18},
                ],
            }
        ],
    }
    words = [
        {"word": "x", "start": 0.0, "end": 0.1},
        {"word": "alpha", "start": 1.0, "end": 1.2},
        {"word": "beta", "start": 2.0, "end": 2.2},
    ]
    out = sync_row_labels_to_whisper_words(spec, words, overwrite=True)
    b = out["rows"][0]["boxes"]
    assert b[0]["wait_word"] == 1
    assert b[1]["wait_word"] == 2


def test_compile_legacy_row_wait_word_fades_each_box() -> None:
    """Row-level ``wait_word`` paces only the first box; every box still gets its own FadeIn."""
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "timing_key": "k",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 0.5,
                "wait_word": 5,
                "boxes": [
                    {"label": "A", "color": "C_GREEN", "width": 2.0, "height": 1.0, "font_size": 18},
                    {"label": "B", "color": "C_BLUE", "width": 2.0, "height": 1.0, "font_size": 18},
                ],
            }
        ],
    }
    out = compile_scene_class(spec)
    assert out.count("wait_until_word(timing_words, 5)") == 1
    assert "FadeIn(_bx_0_0_0)" in out
    assert "FadeIn(_bx_0_0_1)" in out


def test_validate_rejects_row_and_box_wait_word_together() -> None:
    with pytest.raises(SceneSpecError, match="not both"):
        validate_scene_spec(
            {
                "segment_id": "1",
                "class_name": "X",
                "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
                "rows": [
                    {
                        "run_time": 1.0,
                        "wait_word": 0,
                        "boxes": [
                            {
                                "label": "A",
                                "color": "C_GREEN",
                                "width": 2.0,
                                "height": 1.0,
                                "font_size": 18,
                                "wait_word": 1,
                            }
                        ],
                    }
                ],
            }
        )


def test_sync_row_labels_multi_word_phrase_starts_at_first_spoken_word() -> None:
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
    out = sync_row_labels_to_whisper_words(spec, words)
    assert out["rows"][0]["boxes"][0]["wait_word"] == 1
    assert out["rows"][1]["boxes"][0]["wait_word"] == 4


def test_sync_row_labels_stem_match_trace_tracing() -> None:
    """``Trace`` aligns to spoken ``tracing`` without YAML edits."""
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
    out = sync_row_labels_to_whisper_words(spec, words)
    assert out["rows"][0]["boxes"][0]["wait_word"] == 1
    assert out["rows"][1]["boxes"][0]["wait_word"] == 3


def test_sync_row_labels_short_token_tts_strict() -> None:
    """Short product names like ``TTS`` keep strict token equality."""
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
    out = sync_row_labels_to_whisper_words(spec, words)
    assert out["rows"][0]["boxes"][0]["wait_word"] == 1


def test_sync_row_labels_does_not_overwrite_wait_word_unless_forced() -> None:
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {**_row("Whisper"), "wait_word": 99},
        ],
    }
    words = [
        {"word": "noise", "start": 0.0},
        {"word": "Whisper", "start": 1.5},
    ]
    out = sync_row_labels_to_whisper_words(spec, words, overwrite=False)
    assert out["rows"][0]["wait_word"] == 99
    out2 = sync_row_labels_to_whisper_words(spec, words, overwrite=True)
    assert out2["rows"][0]["boxes"][0]["wait_word"] == 1
    assert out2["rows"][0].get("wait_word") is None


def test_sync_row_labels_overwrite_true_fixes_llm_duplicate_wait_words() -> None:
    """Duplicate LLM wait_word indices make wait_until_word a no-op; label sync must replace."""
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {**_row("Whisper"), "wait_word": 0},
            {**_row("Manim"), "wait_word": 0},
            {**_row("Compose"), "wait_word": 0},
        ],
    }
    words = [
        {"word": "the", "start": 0.0, "end": 0.3},
        {"word": "Whisper", "start": 1.5, "end": 1.9},
        {"word": "tool", "start": 2.0, "end": 2.4},
        {"word": "Manim", "start": 3.5, "end": 3.9},
        {"word": "and", "start": 4.0, "end": 4.2},
        {"word": "Compose", "start": 5.5, "end": 5.9},
    ]
    out = sync_row_labels_to_whisper_words(spec, words, overwrite=True)
    assert [out["rows"][i]["boxes"][0].get("wait_word") for i in range(3)] == [1, 3, 5]


def test_sync_row_labels_overwrite_true_clears_unmatched_wait_word() -> None:
    box = {
        "label": "NotInTranscript",
        "color": "C_GREEN",
        "width": 3.0,
        "height": 1.0,
        "font_size": 22,
        "wait_word": 99,
    }
    spec = {
        "segment_id": "1",
        "class_name": "X",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [{"run_time": 1.0, "boxes": [box]}],
    }
    words = [{"word": "hello", "start": 0.0, "end": 0.3}]
    out = sync_row_labels_to_whisper_words(spec, words, overwrite=True)
    assert out["rows"][0]["boxes"][0].get("wait_word") is None
