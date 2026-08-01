"""Tests for offline scene retime + fail-closed pacing in linted_class_block."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.manim_scene_support import BOOTSTRAP_HEADER, SceneGenerationError
from docgen.scene_retime import list_scene_spec_paths, retime_compile_all, retime_compile_spec
from docgen.scene_spec_generate import linted_class_block_from_spec


def _cfg(tmp_path: Path) -> Config:
    raw = {
        "dirs": {
            "narration": "narration",
            "animations": "animations",
            "audio": "audio",
            "recordings": "recordings",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "scene": "DemoScene", "source": "x.mp4"}},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "narration").mkdir()
    (tmp_path / "narration" / "01-demo.md").write_text(
        "Hello world from the demo.\n", encoding="utf-8"
    )
    anim = tmp_path / "animations"
    anim.mkdir()
    (anim / "scenes.py").write_text(BOOTSTRAP_HEADER, encoding="utf-8")
    return Config.from_yaml(p)


def _write_spec(tmp_path: Path, *, label: str = "Hello") -> Path:
    specs = tmp_path / "animations" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    path = specs / "01-demo.scene.yaml"
    path.write_text(
        yaml.dump(
            {
                "segment_id": "01",
                "class_name": "DemoScene",
                "title": {"text": "Demo", "font_size": 36, "color": "C_WHITE"},
                "rows": [
                    {
                        "run_time": 1.0,
                        "boxes": [
                            {
                                "label": label,
                                "color": "C_GREEN",
                                "width": 3.0,
                                "height": 0.9,
                                "font_size": 18,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_timing(tmp_path: Path, words: list[dict]) -> None:
    path = tmp_path / "animations" / "timing.json"
    path.write_text(
        json.dumps(
            {
                "01-demo": {
                    "text": " ".join(w["word"] for w in words),
                    "segments": [{"start": 0.0, "end": 2.0, "text": "hi"}],
                    "words": words,
                }
            }
        ),
        encoding="utf-8",
    )


def test_linted_class_block_fails_closed_on_unmatched_label(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_timing(
        tmp_path,
        [
            {"word": "hello", "start": 0.0, "end": 0.3},
            {"word": "world", "start": 0.4, "end": 0.7},
        ],
    )
    spec = {
        "segment_id": "01",
        "class_name": "DemoScene",
        "title": {"text": "Demo", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "wait_word": 99,
                "boxes": [
                    {
                        "label": "Originator",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 0.9,
                        "font_size": 18,
                    }
                ],
            }
        ],
    }
    with pytest.raises(SceneGenerationError, match="pacing failed|Originator"):
        linted_class_block_from_spec(cfg, spec, timing_key="01-demo")


def test_linted_class_block_succeeds_when_label_spoken(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_timing(
        tmp_path,
        [
            {"word": "Hello", "start": 0.0, "end": 0.3},
            {"word": "world", "start": 0.4, "end": 0.8},
        ],
    )
    spec = {
        "segment_id": "01",
        "class_name": "DemoScene",
        "title": {"text": "Demo", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {
                        "label": "Hello",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 0.9,
                        "font_size": 18,
                    }
                ],
            }
        ],
    }
    block, merged = linted_class_block_from_spec(cfg, spec, timing_key="01-demo")
    assert "wait_until_word(timing_words, 0)" in block
    assert merged["rows"][0]["boxes"][0]["wait_word"] == 0


def test_retime_compile_spec_rewrites_scenes_py(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    path = _write_spec(tmp_path, label="Hello")
    _write_timing(
        tmp_path,
        [
            {"word": "noise", "start": 0.0, "end": 0.2},
            {"word": "Hello", "start": 1.0, "end": 1.3},
        ],
    )
    result = retime_compile_spec(cfg, path)
    assert result["wrote"] is True
    assert result["class_name"] == "DemoScene"
    text = (tmp_path / "animations" / "scenes.py").read_text(encoding="utf-8")
    assert "wait_until_word(timing_words, 1)" in text


def test_retime_compile_all_reports_failures(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write_spec(tmp_path, label="MissingLabel")
    _write_timing(tmp_path, [{"word": "hello", "start": 0.0, "end": 0.2}])
    results, errors = retime_compile_all(cfg)
    assert results == []
    assert errors and "MissingLabel" in errors[0]


def test_list_scene_spec_paths(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert list_scene_spec_paths(cfg) == []
    path = _write_spec(tmp_path)
    assert list_scene_spec_paths(cfg) == [path]
    assert list_scene_spec_paths(cfg, segment_id="01") == [path]
