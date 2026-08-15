"""Pre-render scene asset checks: stuck boards, overlaps, fonts, compile sync."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.manim_scene_support import BOOTSTRAP_HEADER
from docgen.scene_asset_validate import (
    bundle_scene_asset_violations,
    compiled_scene_sync_violations,
    dwell_overshoot_violations,
    helper_api_violations,
    motion_plan_from_source,
    scene_asset_violations_for_segment,
)
from docgen.scene_spec import (
    RevealEvent,
    compile_scene_class,
    simulate_reveal_timeline,
)
from docgen.validate import Validator


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


def _spec(boxes: list[dict], *, class_name: str = "MotionScene") -> dict:
    return {
        "segment_id": "01",
        "class_name": class_name,
        "timing_key": "01-x",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [{"run_time": 1.5, "boxes": boxes}],
    }


def _wide_words() -> list[dict]:
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
    for d in ("narration", "audio", "recordings", "animations"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(tmp_path / "docgen.yaml")


def test_dwell_overshoot_flags_clock_past_next_word() -> None:
    events = [
        RevealEvent(
            label="Alpha",
            page=0,
            row=0,
            box=0,
            wait_word=0,
            word_start=1.0,
            effective_at=1.0,
            wait_skipped=False,
            run_time=0.5,
            page_fade_out=0.0,
            emphasis="pulse",
            dwell_run_time=2.0,
        ),
        RevealEvent(
            label="Beta",
            page=0,
            row=0,
            box=1,
            wait_word=1,
            word_start=1.6,
            effective_at=3.5,
            wait_skipped=True,
            run_time=0.25,
            page_fade_out=0.0,
        ),
    ]
    issues = dwell_overshoot_violations(events)
    assert issues
    assert any("overshoots" in i for i in issues)


def test_dwell_overshoot_clean_when_clamped() -> None:
    spec = _spec([_box("Alpha", wait_word=0), _box("Beta", wait_word=1)])
    events = simulate_reveal_timeline(spec, _wide_words(), clamp_run_times=True)
    assert dwell_overshoot_violations(events) == []


def test_motion_plan_reads_reveal_dwell_and_edge_arrows() -> None:
    src = """
class X(_TimedScene):
    def construct(self):
        _ar_0_0 = _arrow(_bx_0_0_0, _bx_0_0_1, C_ACCENT, style='solid')
        self.wait_until_word(timing_words, 0)
        self.timed_play(GrowFromCenter(_bx_0_0_0), run_time=0.4)
        self.timed_play(Indicate(_bx_0_0_0), run_time=0.5)
        self.wait_until_word(timing_words, 1)
        self.timed_play(FadeIn(_bx_0_0_1), GrowArrow(_ar_0_0), run_time=0.4)
"""
    plan = motion_plan_from_source(src)
    assert plan == [
        "arrow:edge",
        "wait_word:0",
        "reveal:grow:_bx_0_0_0",
        "dwell:pulse:_bx_0_0_0",
        "wait_word:1",
        "reveal:fade:_bx_0_0_1",
        "edge:grow:_ar_0_0",
    ]


def test_motion_plan_flags_center_arrows() -> None:
    src = """
class X(_TimedScene):
    def construct(self):
        _ar_0_0 = _arrow(_bx_0_0_0.get_center(), _bx_0_0_1.get_center(), C_ACCENT)
        self.timed_play(FadeIn(_bx_0_0_0), run_time=0.4)
"""
    assert "arrow:center" in motion_plan_from_source(src)


def test_helper_api_flags_stale_box_and_missing_font() -> None:
    stale = """
def _box(label, color, w=2.2, h=0.75, fs=18):
    return None
def _arrow(start, end, color="#fff"):
    return start
class _TimedScene:
    def timed_play(self, *a, run_time=1.0):
        pass
"""
    issues = helper_api_violations(stale)
    assert any(i.startswith("font:") for i in issues)
    assert any("stale" in i for i in issues)


def test_helper_api_clean_for_current_bootstrap() -> None:
    assert helper_api_violations(BOOTSTRAP_HEADER) == []


def test_compiled_sync_passes_when_scenes_match_compile() -> None:
    spec = _spec([_box("Alpha", wait_word=0), _box("Beta", wait_word=1)])
    words = _wide_words()
    class_src = compile_scene_class(spec, words=words)
    scenes = BOOTSTRAP_HEADER + "\n" + class_src
    assert compiled_scene_sync_violations(spec, words, scenes) == []


def test_compiled_sync_fails_when_indicate_stripped() -> None:
    spec = _spec([_box("Alpha", wait_word=0), _box("Beta", wait_word=1)])
    words = _wide_words()
    class_src = compile_scene_class(spec, words=words)
    stripped = class_src.replace("Indicate", "FadeIn")
    scenes = BOOTSTRAP_HEADER + "\n" + stripped
    issues = compiled_scene_sync_violations(spec, words, scenes)
    assert issues
    assert any("stale" in i for i in issues)


def test_compiled_sync_fails_when_class_missing() -> None:
    spec = _spec([_box("Alpha")])
    issues = compiled_scene_sync_violations(spec, None, BOOTSTRAP_HEADER)
    assert any("not in scenes.py" in i for i in issues)


def test_layout_budget_is_reported_as_overlap(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    specs = cfg.animations_dir / "specs"
    specs.mkdir(parents=True)
    tall = {
        "segment_id": "01",
        "class_name": "MotionScene",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {"run_time": 0.5, "boxes": [_box("A", height=3.0)]},
            {"run_time": 0.5, "boxes": [_box("B", height=3.0)]},
            {"run_time": 0.5, "boxes": [_box("C", height=3.0)]},
        ],
    }
    (specs / "01-x.scene.yaml").write_text(yaml.dump(tall), encoding="utf-8")
    issues = scene_asset_violations_for_segment(cfg, "01")
    assert any(i.startswith("overlap:") for i in issues)


def test_validator_scene_assets_hard_fails_stale_helpers(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    (cfg.animations_dir / "scenes.py").write_text(
        "def _box(label, color, w=1, h=1, fs=18):\n    return None\n"
        "def _arrow(start, end, color='#fff'):\n    return start\n"
        "class _TimedScene:\n    def timed_play(self, *a, run_time=1.0):\n        pass\n",
        encoding="utf-8",
    )
    check = Validator(cfg)._check_scene_assets("01")
    assert not check.passed
    assert any("helpers" in d or "font" in d for d in check.details)


def test_validator_scene_assets_disabled(tmp_path: Path) -> None:
    raw = {
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-x"},
        "visual_map": {"01": {"type": "manim", "scene": "X"}},
        "validation": {"scene_assets": {"enabled": False}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    for d in ("narration", "audio", "recordings", "animations"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    check = Validator(cfg)._check_scene_assets("01")
    assert check.passed
    assert any("disabled" in d for d in check.details)


def test_pre_push_scene_assets_is_hard_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _bundle(tmp_path)
    (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake")
    (cfg.animations_dir / "scenes.py").write_text(
        "def _box(label, color, w=1, h=1, fs=18):\n    return None\n"
        "def _arrow(start, end, color='#fff'):\n    return start\n"
        "class _TimedScene:\n    def timed_play(self, *a, run_time=1.0):\n        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Validator, "_probe_media_duration", staticmethod(lambda p: 10.0))
    (cfg.animations_dir / "timing.json").write_text(
        json.dumps(
            {
                "01-x": {
                    "text": "hello",
                    "words": [{"word": "hello", "start": 0.0, "end": 9.5}],
                    "segments": [{"start": 0.0, "end": 9.5, "text": "hello"}],
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        Validator(cfg).run_pre_push()


def test_bundle_preflight_returns_segment_prefixed_issues(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    (cfg.animations_dir / "scenes.py").write_text(
        "def _box(label, color, w=1, h=1, fs=18):\n    return None\n"
        "def _arrow(start, end, color='#fff'):\n    return start\n"
        "class _TimedScene:\n    def timed_play(self, *a, run_time=1.0):\n        pass\n",
        encoding="utf-8",
    )
    issues = bundle_scene_asset_violations(cfg)
    assert issues
    assert all(i.startswith("[01]") for i in issues)
