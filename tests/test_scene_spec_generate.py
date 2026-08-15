"""Tests for LLM → YAML scene specs (mocked OpenAI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.manim_scene_support import BOOTSTRAP_HEADER, SceneGenerationError
from docgen.scene_spec import layout_stack_budget
from docgen.scene_spec_generate import (
    build_scene_spec_user_message,
    generate_scene_spec,
    inject_class_block_into_scenes_py,
    linted_class_block_from_spec,
    strip_yaml_fences,
)


def _bundle(tmp_path: Path) -> Config:
    cfg = {
        "dirs": {
            "narration": "narration",
            "animations": "animations",
            "audio": "audio",
            "recordings": "recordings",
        },
        "segments": {"default": ["08"], "all": ["08"]},
        "segment_names": {"08": "08-extras"},
        "visual_map": {
            "08": {"type": "manim", "scene": "ExtrasScene", "source": "x.mp4"}
        },
        "manim_scene_generation": {"model": "gpt-4o-mini", "temperature": 0.2},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    narr = tmp_path / "narration"
    narr.mkdir()
    (narr / "08-extras.md").write_text("# Demo\n\nHello world.", encoding="utf-8")
    return Config.from_yaml(p)


MOCK_LLM_YAML = """```yaml
segment_id: "wrong-id"
class_name: WrongClass
title:
  text: "Synthetic"
  font_size: 40
  color: C_WHITE
rows:
  - run_time: 1.2
    boxes:
      - label: "Hello"
        color: C_ORANGE
        width: 4.0
        height: 1.0
        font_size: 20
  - run_time: 1.0
    boxes:
      - label: "world"
        color: C_BLUE
        width: 3.0
        height: 1.0
        font_size: 18
      - label: "Hello world"
        color: C_TEAL
        width: 3.0
        height: 1.0
        font_size: 18
```"""


def test_strip_yaml_fences() -> None:
    body = strip_yaml_fences(MOCK_LLM_YAML)
    assert body.startswith("segment_id:")
    assert "```" not in body


def test_generate_scene_spec_normalizes_ids_and_compiles(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)

    def fake_llm(**_kwargs: object) -> str:
        return MOCK_LLM_YAML

    result = generate_scene_spec(
        cfg,
        "08",
        extra_paths=[],
        extra_hints=[],
        dry_run=False,
        llm=fake_llm,
    )
    assert result.class_name == "ExtrasScene"
    assert result.spec["segment_id"] == "08"
    assert result.spec["class_name"] == "ExtrasScene"
    assert "Hello" in result.yaml_text
    assert "timing_key" not in result.spec


def test_generate_scene_spec_dry_run_no_llm(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    result = generate_scene_spec(
        cfg,
        "08",
        extra_paths=[],
        extra_hints=[],
        dry_run=True,
    )
    assert "Synthetic" not in result.prompt  # user message uses narration
    assert "Hello world" in result.prompt
    assert "SUBJECT BEATS" in result.prompt
    assert "--- system ---" in result.prompt
    assert "shape:" in result.prompt
    assert "reveal:" in result.prompt
    assert "emphasis:" in result.prompt
    assert "dwell_emphasis" in result.prompt
    assert result.yaml_text == ""


def test_generate_scene_spec_retries_when_sparse(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    # Distinct topics → multiple subject beats. MOCK labels (Box A/Left/Right) cover none.
    (tmp_path / "narration" / "08-extras.md").write_text(
        "# Demo\n\n"
        "Alpha lands first on the runway. "
        "Bravo follows with a separate cargo drop. "
        "Charlie closes the triad with radio checks. "
        "Delta keeps the convoy moving east. "
        "Echo wraps the beat near the river. "
        "Foxtrot continues onward past the ridge. "
        "Golf arrives later at the hangar. "
        "Hotel finishes the set after sunset.\n",
        encoding="utf-8",
    )
    calls = {"n": 0}

    def fake_llm(**_kwargs: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return MOCK_LLM_YAML  # invented labels; beats uncovered
        return """```yaml
segment_id: "08"
class_name: ExtrasScene
title:
  text: "Dense"
  font_size: 36
  color: C_WHITE
pages:
  - rows:
      - run_time: 0.8
        boxes:
          - {label: "Alpha lands", color: C_ORANGE, width: 4.0, height: 0.9, font_size: 18}
          - {label: "Bravo follows", color: C_BLUE, width: 4.0, height: 0.9, font_size: 18}
      - run_time: 0.8
        boxes:
          - {label: "Charlie closes", color: C_TEAL, width: 4.0, height: 0.9, font_size: 18}
          - {label: "Delta keeps", color: C_GREEN, width: 4.0, height: 0.9, font_size: 18}
  - rows:
      - run_time: 0.8
        boxes:
          - {label: "Echo wraps", color: C_PURPLE, width: 4.0, height: 0.9, font_size: 18}
          - {label: "Foxtrot continues", color: C_ORANGE, width: 4.0, height: 0.9, font_size: 18}
      - run_time: 0.8
        boxes:
          - {label: "Golf arrives", color: C_BLUE, width: 4.0, height: 0.9, font_size: 18}
          - {label: "Hotel finishes", color: C_TEAL, width: 4.0, height: 0.9, font_size: 18}
```"""

    result = generate_scene_spec(
        cfg,
        "08",
        extra_paths=[],
        extra_hints=[],
        dry_run=False,
        llm=fake_llm,
    )
    assert calls["n"] == 2
    assert result.spec["segment_id"] == "08"
    assert "Hotel finishes" in result.yaml_text


def test_generate_scene_spec_fails_loud_when_narration_missing(tmp_path: Path) -> None:
    p = tmp_path / "docgen.yaml"
    p.write_text(
        yaml.dump(
            {
                "dirs": {
                    "narration": "narration",
                    "animations": "animations",
                    "audio": "audio",
                    "recordings": "recordings",
                },
                "segments": {"default": ["08"], "all": ["08"]},
                "segment_names": {"08": "08-extras"},
                "visual_map": {
                    "08": {"type": "manim", "scene": "ExtrasScene", "source": "x.mp4"}
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "narration").mkdir()
    (tmp_path / "animations").mkdir()
    cfg = Config.from_yaml(p)
    with pytest.raises(SceneGenerationError, match="narration file not found"):
        generate_scene_spec(cfg, "08", extra_paths=[], extra_hints=[])


def test_inject_updates_scenes_py(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    scenes = tmp_path / "animations" / "scenes.py"
    scenes.parent.mkdir(parents=True, exist_ok=True)
    scenes.write_text(BOOTSTRAP_HEADER, encoding="utf-8")

    spec = {
        "segment_id": "08",
        "class_name": "ExtrasScene",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {
                        "label": "One",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 1.0,
                        "font_size": 20,
                    }
                ],
            }
        ],
    }
    block, merged = linted_class_block_from_spec(cfg, spec, timing_key="08-extras")
    assert "class ExtrasScene(_TimedScene):" in block
    assert merged["timing_key"] == "08-extras"

    inject_class_block_into_scenes_py(
        cfg,
        seg_id="08",
        class_name="ExtrasScene",
        class_block=block,
    )
    text = scenes.read_text(encoding="utf-8")
    assert "class ExtrasScene(_TimedScene):" in text
    assert "BEGIN GENERATED SCENE: 08" in text


def test_generate_scene_spec_extra_hints_run_full_pipeline_with_stub_llm(tmp_path: Path) -> None:
    """Same integration intent as a live OpenAI call, but ``llm=`` is injected (no network, no skips)."""
    cfg = _bundle(tmp_path)

    def fake_llm(**_kwargs: object) -> str:
        return MOCK_LLM_YAML

    result = generate_scene_spec(
        cfg,
        "08",
        extra_paths=[],
        extra_hints=["Keep to two rows for a short test."],
        dry_run=False,
        llm=fake_llm,
    )
    assert result.spec["segment_id"] == "08"
    assert result.class_name == "ExtrasScene"
    assert result.spec["rows"]
    assert len(result.spec["rows"]) == 2


def test_user_message_includes_computed_layout_stack_budgets() -> None:
    budget_default = layout_stack_budget(
        {"font_size": 36}, {"first_row_title_buff": 0.5}
    )
    budget_compact = layout_stack_budget(
        {"font_size": 32}, {"first_row_title_buff": 0.45}
    )
    msg = build_scene_spec_user_message(
        seg_id="01",
        seg_name="01-x",
        class_name="XScene",
        narration_text="Hello world.",
        timing_enrichment="(no timing)",
        hints=[],
        extra_hints=[],
        reference_scenes="",
        source_snippets=[],
    )
    assert "FRAME / LAYOUT BUDGET" in msg
    assert f"{budget_default:.2f}" in msg
    assert f"{budget_compact:.2f}" in msg
    assert "13.22" in msg  # horizontal safe width (FRAME_WIDTH - 1.0)
