"""Paced bar and line chart pages."""

from __future__ import annotations

import pytest

from docgen.scene_asset_validate import motion_plan_from_source
from docgen.scene_chart import chart_value_violations, materialize_charts
from docgen.scene_clock_harness import (
    run_compiled_scene_clock,
    simulator_exec_drift_violations,
)
from docgen.scene_spec import (
    SceneSpecError,
    auto_paginate,
    compile_scene_class,
    layout_density_violations,
    list_spec_labels,
    pacing_violations,
    simulate_reveal_timeline,
    sync_row_labels_to_whisper_words,
    validate_scene_spec,
)
from docgen.scene_spec_generate import _SCENE_SPEC_SYSTEM_BASE


def _title() -> dict:
    return {"text": "Counts", "font_size": 36, "color": "C_WHITE"}


def _bar_spec(*series: dict) -> dict:
    return {
        "segment_id": "01",
        "class_name": "ChartScene",
        "timing_key": "01-chart",
        "title": _title(),
        "pages": [{"chart": {"kind": "bar", "series": list(series)}}],
    }


def _line_spec(*series: dict) -> dict:
    spec = _bar_spec(*series)
    spec["pages"][0]["chart"]["kind"] = "line"
    return spec


def _pair() -> list[dict]:
    return [
        {"label": "Build", "value": 12, "color": "C_GREEN"},
        {"label": "Ship", "value": 4, "color": "C_BLUE"},
    ]


def _words() -> list[dict]:
    return [
        {"word": "Build", "start": 1.2, "end": 1.5},
        {"word": "Ship", "start": 6.0, "end": 6.3},
        {"word": "tail", "start": 10.0, "end": 10.4},
    ]


def _narration() -> str:
    return "Build finished in 12 minutes. Ship finished in 4 minutes."


def test_prompt_mentions_chart_pages() -> None:
    assert "kind: bar" in _SCENE_SPEC_SYSTEM_BASE
    assert "kind: line" in _SCENE_SPEC_SYSTEM_BASE


def test_validate_accepts_bar_and_line_and_keeps_authoring() -> None:
    spec = _bar_spec(*_pair())
    validate_scene_spec(spec)
    assert "chart" in spec["pages"][0]
    assert "rows" not in spec["pages"][0]
    line = _line_spec(*_pair())
    validate_scene_spec(line)
    labels = list_spec_labels(spec)
    assert labels == ["Build", "Ship"]


def test_chart_schema_rejects() -> None:
    both = _bar_spec(*_pair())
    both["pages"][0]["rows"] = [{"run_time": 0.5, "boxes": []}]
    with pytest.raises(SceneSpecError, match="not both"):
        validate_scene_spec(both)

    edged = _bar_spec(*_pair())
    edged["pages"][0]["edges"] = [{"from": "Build", "to": "Ship"}]
    with pytest.raises(SceneSpecError, match="do not take edges"):
        validate_scene_spec(edged)

    pie = _bar_spec(*_pair())
    pie["pages"][0]["chart"]["kind"] = "pie"
    with pytest.raises(SceneSpecError, match="bar or line"):
        validate_scene_spec(pie)

    zero = _bar_spec({"label": "Build", "value": 0})
    with pytest.raises(SceneSpecError, match="positive"):
        validate_scene_spec(zero)

    word = _bar_spec({"label": "Build", "value": True})
    with pytest.raises(SceneSpecError, match="positive"):
        validate_scene_spec(word)

    dup = _bar_spec(
        {"label": "Build", "value": 2},
        {"label": "Build", "value": 3},
    )
    with pytest.raises(SceneSpecError, match="duplicate"):
        validate_scene_spec(dup)

    too_many = _bar_spec(*[{"label": f"N{i}", "value": i + 1} for i in range(7)])
    with pytest.raises(SceneSpecError, match="at most 6"):
        validate_scene_spec(too_many)


def test_digits_must_appear_in_the_narration() -> None:
    spec = _bar_spec(*_pair())
    assert chart_value_violations(spec, _narration()) == []
    assert chart_value_violations(spec, "Build took twelve minutes. Ship took 4.")
    issues = layout_density_violations(
        spec, narration_text="Build took twelve minutes. Ship took 4 minutes."
    )
    assert any("value 12" in item for item in issues)
    assert not any("value 4" in item for item in issues)
    # 12.5 does not document 12. A trailing period does.
    assert chart_value_violations(spec, "Build took 12.5 minutes. Ship took 4.")
    assert chart_value_violations(spec, "Build took 12. Ship took 4.") == []
    assert chart_value_violations(spec, "Build took 120 minutes. Ship took 4.")


def test_bars_grow_one_at_a_time() -> None:
    spec = _bar_spec(*_pair())
    out = compile_scene_class(spec, words=_words())
    grows = [line.strip() for line in out.splitlines() if "GrowFromEdge" in line]
    assert len(grows) == 2
    assert "GrowFromEdge(_bx_0_0_0, LEFT)" in grows[0]
    assert "GrowFromEdge(_bx_0_1_0, LEFT)" in grows[1]
    assert "Text('12'" in out
    assert "Text('4'" in out
    assert "aligned_edge=LEFT" in out
    plan = motion_plan_from_source(out)
    assert "reveal:bar:_bx_0_0_0" in plan
    assert "reveal:bar:_bx_0_1_0" in plan
    assert plan.index("reveal:bar:_bx_0_0_0") < plan.index("reveal:bar:_bx_0_1_0")


def test_line_draws_each_segment_with_its_point() -> None:
    spec = _line_spec(*_pair(), {"label": "Run", "value": 9, "color": "C_ORANGE"})
    words = [
        {"word": "Build", "start": 1.2, "end": 1.5},
        {"word": "Ship", "start": 6.0, "end": 6.3},
        {"word": "Run", "start": 9.0, "end": 9.3},
        {"word": "tail", "start": 13.0, "end": 13.4},
    ]
    out = compile_scene_class(spec, words=words)
    fades = [line for line in out.splitlines() if "FadeIn(_bx_" in line]
    assert len(fades) == 3
    assert "Create(" not in fades[0]
    assert "Create(_ln_0_1)" in fades[1]
    assert "Create(_ln_0_2)" in fades[2]
    assert "Dot(point=" in out
    plan = motion_plan_from_source(out)
    assert "edge:draw:_ln_0_1" in plan
    assert "edge:draw:_ln_0_2" in plan


def test_slide_handoff_keeps_later_bars_paced() -> None:
    spec = {
        "segment_id": "01",
        "class_name": "ChartScene",
        "timing_key": "01-chart",
        "title": _title(),
        "pages": [
            {
                "rows": [
                    {
                        "run_time": 0.6,
                        "boxes": [
                            {
                                "label": "Intro",
                                "color": "C_WHITE",
                                "width": 3.0,
                                "height": 0.8,
                                "font_size": 18,
                            }
                        ],
                    }
                ]
            },
            {
                "transition": "slide",
                "chart": {"kind": "bar", "series": _pair()},
            },
        ],
    }
    words = [
        {"word": "Intro", "start": 1.2, "end": 1.5},
        {"word": "Build", "start": 5.0, "end": 5.3},
        {"word": "Ship", "start": 8.0, "end": 8.3},
        {"word": "tail", "start": 12.0, "end": 12.4},
    ]
    out = compile_scene_class(spec, words=words)
    assert "FadeOut(_bx_0_0_0, shift=LEFT *" in out
    entered = [
        line for line in out.splitlines() if "FadeIn(_bx_1_0_0" in line and "shift=LEFT" in line
    ]
    assert entered
    assert "GrowFromEdge" not in entered[0]
    assert any("GrowFromEdge(_bx_1_1_0, LEFT)" in line for line in out.splitlines())


def test_chart_clock_does_not_skip_words() -> None:
    spec = _bar_spec(*_pair())
    words = _words()
    out = compile_scene_class(spec, words=words)
    trace = run_compiled_scene_clock(out, words)
    assert trace.skipped_waits() == []
    events = simulate_reveal_timeline(spec, words)
    assert simulator_exec_drift_violations(events, trace) == []
    grows = [e for e in trace.reveal_plays() if "GrowFromEdge" in e.anim_kinds]
    assert len(grows) == 2


def test_sync_and_pacing_see_series_labels() -> None:
    spec = _bar_spec(*_pair())
    synced = sync_row_labels_to_whisper_words(spec, _words(), overwrite=True)
    labels = list_spec_labels(synced)
    assert labels == ["Build", "Ship"]
    assert pacing_violations(synced, words_present=True) == []
    bare = materialize_charts(spec)
    assert bare["pages"][0]["rows"][0]["boxes"][0]["chart_kind"] == "bar"
    assert pacing_violations(spec, words_present=True)


def test_auto_paginate_keeps_chart_pages_whole() -> None:
    tall = {
        "run_time": 0.5,
        "boxes": [
            {
                "label": "Row",
                "color": "C_GREEN",
                "width": 3.0,
                "height": 2.0,
                "font_size": 18,
            }
        ],
    }
    spec = {
        "segment_id": "01",
        "class_name": "ChartScene",
        "timing_key": "01-chart",
        "title": _title(),
        "pages": [
            {"chart": {"kind": "bar", "series": _pair()}},
            {"transition": "slide", "rows": [tall, tall, tall, tall, tall, tall]},
        ],
    }
    out = auto_paginate(spec)
    assert out["pages"][0]["chart"]["kind"] == "bar"
    assert "rows" not in out["pages"][0]
    assert len(out["pages"]) > 2
    assert out["pages"][1]["transition"] == "slide"


def test_density_accepts_spoken_chart_labels() -> None:
    spec = _bar_spec(*_pair())
    issues = layout_density_violations(spec, narration_text=_narration())
    assert issues == []
