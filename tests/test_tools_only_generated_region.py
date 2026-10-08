"""CI gate: a hand-edit inside BEGIN/END GENERATED SCENE fails scene_assets.

Temp fixture only. Does not use an in-repo dogfood bundle.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from docgen.config import Config
from docgen.manim_scene_support import BOOTSTRAP_HEADER, inject_or_replace
from docgen.scene_spec import compile_scene_class
from docgen.validate import Validator

ROOT = Path(__file__).resolve().parents[1]


def _box(label: str, **extra: object) -> dict:
    out: dict = {
        "label": label,
        "color": "C_GREEN",
        "width": 3.0,
        "height": 0.8,
        "font_size": 18,
    }
    out.update(extra)
    return out


def _spec() -> dict:
    return {
        "segment_id": "01",
        "class_name": "MotionScene",
        "timing_key": "01-x",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.5,
                "boxes": [_box("Alpha", wait_word=0), _box("Beta", wait_word=1)],
            }
        ],
    }


def _words() -> list[dict]:
    return [
        {"word": "Alpha", "start": 1.2, "end": 1.4},
        {"word": "Beta", "start": 8.0, "end": 8.3},
        {"word": "tail", "start": 16.0, "end": 16.4},
    ]


def _bundle(tmp_path: Path) -> Config:
    raw = {
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-x"},
        "visual_map": {"01": {"type": "manim", "scene": "MotionScene"}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    for name in ("narration", "audio", "recordings", "animations"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(tmp_path / "docgen.yaml")


def _region_span(text: str) -> tuple[int, int]:
    begin = text.index("# ── BEGIN GENERATED SCENE: 01 (MotionScene) ──")
    end = text.index("# ── END GENERATED SCENE: 01 ──")
    end += len("# ── END GENERATED SCENE: 01 ──")
    assert begin < end
    return begin, end


def _write_compiled_region(cfg: Config) -> str:
    spec = _spec()
    words = _words()
    specs = cfg.animations_dir / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "01-x.scene.yaml").write_text(yaml.dump(spec), encoding="utf-8")
    (cfg.animations_dir / "timing.json").write_text(
        json.dumps(
            {
                "01-x": {
                    "text": "Alpha Beta tail",
                    "words": words,
                    "segments": [{"start": 1.2, "end": 16.4, "text": "Alpha Beta tail"}],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    class_src = compile_scene_class(spec, words=words)
    scenes = inject_or_replace(BOOTSTRAP_HEADER + "\n", "01", "MotionScene", class_src)
    (cfg.animations_dir / "scenes.py").write_text(scenes, encoding="utf-8")
    return scenes


def _assert_region_drift_fails(cfg: Config, scenes: str, region: str) -> None:
    begin, end = _region_span(scenes)
    tampered = scenes[:begin] + region + scenes[end:]
    assert tampered[:begin] == scenes[:begin]
    assert tampered[begin + len(region) :] == scenes[end:]
    (cfg.animations_dir / "scenes.py").write_text(tampered, encoding="utf-8")
    check = Validator(cfg)._check_scene_assets("01")
    assert not check.passed
    assert any("compile_sync" in detail and "stale" in detail for detail in check.details)


def test_hand_edited_generated_region_fails_scene_assets(tmp_path: Path) -> None:
    """Label or run_time drift inside the generated region fails scene_assets."""
    cfg = _bundle(tmp_path)
    scenes = _write_compiled_region(cfg)
    begin, end = _region_span(scenes)
    region = scenes[begin:end]
    assert "class MotionScene" in region
    assert "'Alpha'" in region

    clean = Validator(cfg)._check_scene_assets("01")
    assert clean.passed, clean.details

    label_region = region.replace("'Alpha'", "'Hacked'", 1)
    assert "'Hacked'" in label_region
    assert "'Hacked'" not in scenes[:begin]
    _assert_region_drift_fails(cfg, scenes, label_region)

    run_time_region, replacements = re.subn(
        r"run_time=\d+(?:\.\d+)?",
        "run_time=9.99",
        region,
        count=1,
    )
    assert replacements == 1
    assert "run_time=9.99" not in scenes[:begin]
    _assert_region_drift_fails(cfg, scenes, run_time_region)


def test_ci_unit_job_runs_hand_edited_generated_region() -> None:
    """The unit job's pytest tests/ run collects this module."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    unit = text.split("\n  unit:", 1)[1].split("\n  benchmark:", 1)[0]
    assert "pytest tests/" in unit
    module = ROOT / "tests" / "test_tools_only_generated_region.py"
    assert module.is_file()
    source = module.read_text(encoding="utf-8")
    assert "def test_hand_edited_generated_region_fails_scene_assets" in source
