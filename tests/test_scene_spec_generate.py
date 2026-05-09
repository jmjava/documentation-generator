"""Tests for LLM → YAML scene specs (mocked OpenAI)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.scene_generate import BOOTSTRAP_HEADER
from docgen.scene_spec_generate import (
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
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"default": ["08"], "all": ["08"]},
        "segment_names": {"08": "08-demo-function"},
        "visual_map": {
            "08": {"type": "manim", "scene": "DemoFunctionScene", "source": "x.mp4"}
        },
        "manim_scene_generation": {"model": "gpt-4o-mini", "temperature": 0.2},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    narr = tmp_path / "narration"
    narr.mkdir()
    (narr / "08-demo-function.md").write_text("# Demo\n\nHello world.", encoding="utf-8")
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
      - label: "Box A"
        color: C_ORANGE
        width: 4.0
        height: 1.0
        font_size: 20
  - run_time: 1.0
    boxes:
      - label: "Left"
        color: C_BLUE
        width: 3.0
        height: 1.0
        font_size: 18
      - label: "Right"
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
    assert result.class_name == "DemoFunctionScene"
    assert result.spec["segment_id"] == "08"
    assert result.spec["class_name"] == "DemoFunctionScene"
    assert "Box A" in result.yaml_text
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
    assert "--- system ---" in result.prompt
    assert result.yaml_text == ""


def test_inject_updates_scenes_py(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    scenes = tmp_path / "animations" / "scenes.py"
    scenes.parent.mkdir(parents=True, exist_ok=True)
    scenes.write_text(BOOTSTRAP_HEADER, encoding="utf-8")

    spec = {
        "segment_id": "08",
        "class_name": "DemoFunctionScene",
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
    block, merged = linted_class_block_from_spec(cfg, spec, timing_key="08-demo-function")
    assert "class DemoFunctionScene(_TimedScene):" in block
    assert merged["timing_key"] == "08-demo-function"

    inject_class_block_into_scenes_py(
        cfg,
        seg_id="08",
        class_name="DemoFunctionScene",
        class_block=block,
    )
    text = scenes.read_text(encoding="utf-8")
    assert "class DemoFunctionScene(_TimedScene):" in text
    assert "BEGIN GENERATED SCENE: 08" in text


@pytest.mark.integration
def test_scene_spec_generate_live_openai(tmp_path: Path) -> None:
    import os

    if os.environ.get("DOCGEN_RUN_LIVE_OPENAI") != "1":
        pytest.skip("set DOCGEN_RUN_LIVE_OPENAI=1 and OPENAI_API_KEY for live LLM test")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")

    cfg = _bundle(tmp_path)
    result = generate_scene_spec(
        cfg,
        "08",
        extra_paths=[],
        extra_hints=["Keep to two rows for a short test."],
        dry_run=False,
    )
    assert result.spec["segment_id"] == "08"
    assert result.class_name == "DemoFunctionScene"
    assert result.spec["rows"]
