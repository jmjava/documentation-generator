"""Clock-safe dwell, box motion fields, and connector geometry."""

from __future__ import annotations

import pytest

from docgen.manim_primitives import connector_endpoints
from docgen.scene_spec import (
    DEFAULT_DWELL_RUN_TIME,
    MIN_DWELL_RUN_TIME,
    MIN_REVEAL_RUN_TIME,
    SceneSpecError,
    compile_scene_class,
    compute_dwell_run_time,
    resolve_box_emphasis,
    simulate_reveal_timeline,
    validate_scene_spec,
)


def _box(
    label: str,
    *,
    wait_word: int | None = None,
    emphasis: str | None = None,
    reveal: str | None = None,
    shape: str | None = None,
    subtitle: str | None = None,
) -> dict:
    out: dict = {
        "label": label,
        "color": "C_GREEN",
        "width": 3.0,
        "height": 0.8,
        "font_size": 18,
    }
    if wait_word is not None:
        out["wait_word"] = wait_word
    if emphasis is not None:
        out["emphasis"] = emphasis
    if reveal is not None:
        out["reveal"] = reveal
    if shape is not None:
        out["shape"] = shape
    if subtitle is not None:
        out["subtitle"] = subtitle
    return out


def _spec(boxes: list[dict], *, layout: dict | None = None) -> dict:
    spec: dict = {
        "segment_id": "01",
        "class_name": "MotionScene",
        "timing_key": "01-motion",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [{"run_time": 1.5, "boxes": boxes}],
    }
    if layout:
        spec["layout"] = layout
    return spec


def _wide_words() -> list[dict]:
    """Long holds between spoken labels — dwell should fire."""
    return [
        {"word": "Alpha", "start": 1.2, "end": 1.4},
        {"word": "Beta", "start": 8.0, "end": 8.3},
        {"word": "Gamma", "start": 16.0, "end": 16.3},
        {"word": "tail", "start": 24.0, "end": 24.4},
    ]


def _tight_words() -> list[dict]:
    return [
        {"word": "Alpha", "start": 1.2, "end": 1.4},
        {"word": "Beta", "start": 1.6, "end": 1.8},
        {"word": "Gamma", "start": 2.0, "end": 2.2},
        {"word": "tail", "start": 40.0, "end": 40.5},
    ]


def test_compute_dwell_zero_when_emphasis_none() -> None:
    assert compute_dwell_run_time(1.0, 10.0, requested="none") == 0.0


def test_compute_dwell_zero_when_gap_too_tight() -> None:
    # clock=1.45, next=1.6 → usable < MIN_DWELL_RUN_TIME
    assert compute_dwell_run_time(1.45, 1.6, requested="pulse") == 0.0


def test_compute_dwell_clamps_to_default_on_wide_gap() -> None:
    rt = compute_dwell_run_time(2.0, 12.0, requested="pulse")
    assert rt == pytest.approx(DEFAULT_DWELL_RUN_TIME)
    assert rt >= MIN_DWELL_RUN_TIME


def test_compute_dwell_last_box_uses_default() -> None:
    rt = compute_dwell_run_time(20.0, None, requested="ring")
    assert rt == pytest.approx(DEFAULT_DWELL_RUN_TIME)


def test_compute_dwell_shrinks_when_next_beat_is_close_but_usable() -> None:
    # clock=5.0, next=5.7, margin 0.12 → usable 0.58, default 0.5 → 0.5
    rt = compute_dwell_run_time(5.0, 5.7, requested="pulse")
    assert MIN_DWELL_RUN_TIME <= rt <= 0.58


def test_resolve_box_emphasis_inherit_auto_is_pulse() -> None:
    assert resolve_box_emphasis({}, {}) == "pulse"
    assert resolve_box_emphasis({}, {"dwell_emphasis": "auto"}) == "pulse"


def test_resolve_box_emphasis_layout_none() -> None:
    assert resolve_box_emphasis({}, {"dwell_emphasis": "none"}) == "none"


def test_resolve_box_emphasis_box_overrides_layout() -> None:
    assert resolve_box_emphasis({"emphasis": "ring"}, {"dwell_emphasis": "none"}) == "ring"
    assert resolve_box_emphasis({"emphasis": "none"}, {"dwell_emphasis": "auto"}) == "none"


def test_wide_holds_get_pulse_dwell_without_skipping_waits() -> None:
    spec = _spec([_box("Alpha", wait_word=0), _box("Beta", wait_word=1), _box("Gamma", wait_word=2)])
    events = simulate_reveal_timeline(spec, _wide_words(), clamp_run_times=True)
    assert len(events) == 3
    assert all(not e.wait_skipped for e in events[1:])
    # First two have a long gap to the next word; last box still dwells (audio tail).
    assert events[0].dwell_run_time >= MIN_DWELL_RUN_TIME
    assert events[1].dwell_run_time >= MIN_DWELL_RUN_TIME
    assert events[2].dwell_run_time >= MIN_DWELL_RUN_TIME
    assert all(e.emphasis == "pulse" for e in events)
    # Clock after fade+dwell must stay behind the next spoken start.
    assert events[0].effective_at + events[0].run_time + events[0].dwell_run_time < 8.0
    assert events[1].effective_at + events[1].run_time + events[1].dwell_run_time < 16.0


def test_tight_cascade_gets_no_dwell() -> None:
    spec = _spec([_box("Alpha", wait_word=0), _box("Beta", wait_word=1), _box("Gamma", wait_word=2)])
    events = simulate_reveal_timeline(spec, _tight_words(), clamp_run_times=True)
    assert all(e.dwell_run_time == 0.0 for e in events[:-1])
    assert all(e.run_time >= MIN_REVEAL_RUN_TIME for e in events)
    assert not events[1].wait_skipped
    assert not events[2].wait_skipped


def test_emphasis_none_suppresses_dwell_on_wide_holds() -> None:
    spec = _spec(
        [
            _box("Alpha", wait_word=0, emphasis="none"),
            _box("Beta", wait_word=1, emphasis="none"),
        ]
    )
    events = simulate_reveal_timeline(spec, _wide_words(), clamp_run_times=True)
    assert all(e.dwell_run_time == 0.0 for e in events)
    assert all(e.emphasis == "none" for e in events)


def test_layout_dwell_emphasis_none_disables_auto() -> None:
    spec = _spec(
        [_box("Alpha", wait_word=0), _box("Beta", wait_word=1)],
        layout={"dwell_emphasis": "none"},
    )
    events = simulate_reveal_timeline(spec, _wide_words(), clamp_run_times=True)
    assert all(e.dwell_run_time == 0.0 for e in events)


def test_compile_wide_holds_emits_indicate() -> None:
    spec = _spec([_box("Alpha", wait_word=0), _box("Beta", wait_word=1)])
    out = compile_scene_class(spec, words=_wide_words())
    assert "Indicate(_bx_0_0_0)" in out
    assert "wait_until_word(timing_words, 1)" in out
    fade_at = out.index("FadeIn(_bx_0_0_0)")
    pulse_at = out.index("Indicate(_bx_0_0_0)")
    next_wait = out.index("wait_until_word(timing_words, 1)")
    assert fade_at < pulse_at < next_wait


def test_compile_ring_emits_circumscribe() -> None:
    spec = _spec([_box("Alpha", wait_word=0, emphasis="ring"), _box("Beta", wait_word=1)])
    out = compile_scene_class(spec, words=_wide_words())
    assert "Circumscribe(_bx_0_0_0)" in out
    assert "Indicate(_bx_0_0_0)" not in out


def test_compile_without_words_emits_no_dwell() -> None:
    spec = _spec([_box("Alpha"), _box("Beta")])
    out = compile_scene_class(spec)
    assert "Indicate(" not in out
    assert "Circumscribe(" not in out


def test_compile_reveal_grow_and_slide() -> None:
    spec = _spec(
        [
            _box("Alpha", wait_word=0, reveal="grow"),
            _box("Beta", wait_word=1, reveal="slide"),
        ]
    )
    out = compile_scene_class(spec, words=_wide_words())
    assert "GrowFromCenter(_bx_0_0_0)" in out
    assert "FadeIn(_bx_0_0_1, shift=UP * 0.22)" in out


def test_compile_shape_and_default_omitted() -> None:
    spec = _spec(
        [
            _box("Alpha", shape="diamond"),
            _box("Beta", shape="pill"),
            _box("Gamma"),
        ]
    )
    out = compile_scene_class(spec)
    assert "shape='diamond'" in out
    assert "shape='pill'" in out
    assert "shape='rounded'" not in out
    assert "_box('Gamma', C_GREEN, 3.0, 0.8, 18)" in out


def test_compile_edges_pass_mobjects_not_centers() -> None:
    spec = {
        "segment_id": "01",
        "class_name": "FlowScene",
        "timing_key": "01-flow",
        "title": {"text": "Flow", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 0.8,
                "boxes": [
                    _box("Hints", wait_word=0),
                    _box("YAML", wait_word=1),
                ],
            }
        ],
        "edges": [{"from": "Hints", "to": "YAML", "color": "C_ACCENT"}],
    }
    spec["rows"][0]["boxes"][1]["color"] = "C_BLUE"
    out = compile_scene_class(spec)
    assert "_arrow(_bx_0_0_0, _bx_0_0_1, C_ACCENT, style='solid')" in out
    assert ".get_center()" not in out


def test_validate_rejects_unknown_shape_reveal_emphasis() -> None:
    with pytest.raises(SceneSpecError, match="shape"):
        validate_scene_spec(_spec([_box("A", shape="hexagon")]))
    with pytest.raises(SceneSpecError, match="reveal"):
        validate_scene_spec(_spec([_box("A", reveal="explode")]))
    with pytest.raises(SceneSpecError, match="emphasis"):
        validate_scene_spec(_spec([_box("A", emphasis="sparkle")]))


def test_validate_rejects_bad_layout_dwell_fields() -> None:
    with pytest.raises(SceneSpecError, match="dwell_emphasis"):
        validate_scene_spec(_spec([_box("A")], layout={"dwell_emphasis": "loud"}))
    with pytest.raises(SceneSpecError, match="dwell_run_time"):
        validate_scene_spec(_spec([_box("A")], layout={"dwell_run_time": 0}))


def test_connector_endpoints_are_on_facing_edges() -> None:
    start, end = connector_endpoints((0.0, 0.0), (1.0, 0.4), (4.0, 0.0), (1.0, 0.4), buff=0.2)
    # Source right edge is x=1.0; dest left edge is x=3.0; buff pushes inward-to-gap.
    assert start[0] == pytest.approx(1.2)
    assert end[0] == pytest.approx(2.8)
    assert start[1] == pytest.approx(0.0)
    assert end[1] == pytest.approx(0.0)


def test_connector_endpoints_vertical_stack() -> None:
    start, end = connector_endpoints((0.0, 2.0), (1.0, 0.5), (0.0, -2.0), (1.0, 0.5), buff=0.1)
    assert start[0] == pytest.approx(0.0)
    assert end[0] == pytest.approx(0.0)
    assert start[1] == pytest.approx(1.4)  # 2.0 - 0.5 - 0.1
    assert end[1] == pytest.approx(-1.4)
