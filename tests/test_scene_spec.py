"""Unit tests for declarative scene YAML → Manim class compilation."""

from __future__ import annotations

from pathlib import Path

import pytest

from docgen.scene_spec import (
    SceneSpecError,
    compile_scene_class,
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
    assert "_bx_0_0 = _box('Alpha', C_ORANGE, 5.0, 1.2, 28)" in out
    assert "_bx_1_0 = _box('Beta', C_BLUE, 3.5, 1.2, 24)" in out
    assert "_row_1 = VGroup(_bx_1_0, _bx_1_1).arrange(RIGHT, buff=0.35).next_to(_bx_0_0, DOWN, buff=0.35)" in out
    assert "self.timed_play(FadeIn(_bx_0_0), run_time=1.0)" in out
    assert "self.timed_play(FadeIn(_row_1), run_time=1.0)" in out


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


def test_compile_requires_timing_key() -> None:
    raw = load_scene_spec(FIXTURE)
    with pytest.raises(SceneSpecError, match="timing_key"):
        compile_scene_class(raw)
