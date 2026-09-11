"""Tests for the ``timing_sync`` validation check (audio ↔ timing.json staleness)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.validate import Validator


def _bundle(tmp_path: Path, *, visual_type: str = "manim") -> Config:
    raw = {
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-x"},
        "visual_map": {"01": {"type": visual_type, "class": "XScene"}},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    for d in ("narration", "audio", "recordings", "animations"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(tmp_path / "docgen.yaml")


def _write_timing(cfg: Config, last_end: float) -> None:
    block = {
        "text": "hello world",
        "segments": [{"start": 0.0, "end": last_end, "text": "hello world"}],
        "words": [
            {"start": 0.0, "end": last_end / 2, "word": "hello"},
            {"start": last_end / 2, "end": last_end, "word": "world"},
        ],
    }
    (cfg.animations_dir / "timing.json").write_text(
        json.dumps({"01-x": block}), encoding="utf-8"
    )


def _patch_audio_duration(monkeypatch, seconds: float | None) -> None:
    monkeypatch.setattr(
        Validator, "_probe_media_duration", staticmethod(lambda p: seconds)
    )


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = _bundle(tmp_path)
    (c.audio_dir / "01-x.mp3").write_bytes(b"fake mp3 bytes")
    return c


class TestTimingSync:
    @pytest.mark.parametrize("bad, kind", ((float("nan"), "NaN"), (float("inf"), "Infinity")))
    def test_non_finite_word_start_fails(self, cfg, monkeypatch, bad: float, kind: str) -> None:
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps(
                {
                    "01-x": {
                        "text": "hello",
                        "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}],
                        "words": [{"start": bad, "end": 1.0, "word": "hello"}],
                    }
                },
                allow_nan=True,
            ),
            encoding="utf-8",
        )
        _patch_audio_duration(monkeypatch, 1.2)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any(kind in d for d in check.details)

    def test_fresh_timing_passes(self, cfg, monkeypatch) -> None:
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 10.4)
        check = Validator(cfg)._check_timing_sync("01")
        assert check.passed, check.details

    def test_unprobed_audio_duration_fails(self, cfg, monkeypatch) -> None:
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, None)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("cannot probe audio duration" in d for d in check.details)

    def test_audio_much_longer_than_transcript_fails(self, cfg, monkeypatch) -> None:
        """Regenerated (longer) mp3 with old timing.json → stale."""
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 30.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("stale" in d for d in check.details)

    def test_transcript_past_audio_end_fails(self, cfg, monkeypatch) -> None:
        """Regenerated (shorter) mp3 with old timing.json → stale."""
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 7.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("stale" in d for d in check.details)

    def test_missing_timing_entry_fails_for_manim(self, cfg, monkeypatch) -> None:
        (cfg.animations_dir / "timing.json").write_text("{}", encoding="utf-8")
        _patch_audio_duration(monkeypatch, 10.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("docgen timestamps" in d for d in check.details)

    def test_corrupt_timing_json_fails_for_manim(self, cfg, monkeypatch) -> None:
        (cfg.animations_dir / "timing.json").write_text("{not json", encoding="utf-8")
        _patch_audio_duration(monkeypatch, 10.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("not valid JSON" in d for d in check.details)

    def test_non_object_timing_stem_fails_for_manim(self, cfg, monkeypatch) -> None:
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps({"01-x": [1, 2, 3]}) + "\n", encoding="utf-8"
        )
        _patch_audio_duration(monkeypatch, 10.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("timing.json['01-x'] must be a JSON object" in d for d in check.details)

    def test_non_array_timing_words_fails_for_manim(self, cfg, monkeypatch) -> None:
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps({"01-x": {"words": {"word": "hello"}, "segments": []}}) + "\n",
            encoding="utf-8",
        )
        _patch_audio_duration(monkeypatch, 10.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert not check.passed
        assert any("timing.json['01-x'].words must be a JSON array" in d for d in check.details)



    def test_missing_timing_entry_skips_for_non_manim(self, tmp_path, monkeypatch) -> None:
        cfg = _bundle(tmp_path, visual_type="still")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake mp3 bytes")
        _patch_audio_duration(monkeypatch, 10.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert check.passed

    def test_no_audio_skips(self, tmp_path) -> None:
        cfg = _bundle(tmp_path)
        check = Validator(cfg)._check_timing_sync("01")
        assert check.passed
        assert any("skipped" in d.lower() for d in check.details)

    def test_disabled_via_config(self, tmp_path, monkeypatch) -> None:
        cfg = _bundle(tmp_path)
        raw = yaml.safe_load((tmp_path / "docgen.yaml").read_text())
        raw["validation"] = {"timing_sync": {"enabled": False}}
        (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake mp3 bytes")
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 99.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert check.passed
        assert any("disabled" in d for d in check.details)

    def test_threshold_configurable(self, tmp_path, monkeypatch) -> None:
        raw = {
            "segments": {"default": ["01"], "all": ["01"]},
            "segment_names": {"01": "01-x"},
            "visual_map": {"01": {"type": "manim", "class": "XScene"}},
            "validation": {"timing_sync": {"max_tail_gap_sec": 25.0}},
        }
        (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
        for d in ("audio", "animations"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake mp3 bytes")
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 30.0)
        check = Validator(cfg)._check_timing_sync("01")
        assert check.passed, check.details

    def test_timing_sync_is_hard_fail_in_pre_push(self, cfg, monkeypatch) -> None:
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 30.0)
        v = Validator(cfg)
        with pytest.raises(SystemExit):
            v.run_pre_push()


def _write_scene_spec(cfg: Config, *, labels: list[str]) -> None:
    specs = cfg.animations_dir / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    boxes = [
        {
            "label": lab,
            "color": "C_GREEN",
            "width": 3.0,
            "height": 1.0,
            "font_size": 18,
        }
        for lab in labels
    ]
    raw = {
        "segment_id": "01",
        "class_name": "XScene",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [{"run_time": 1.0, "boxes": boxes}],
    }
    (specs / "01-x.scene.yaml").write_text(yaml.dump(raw), encoding="utf-8")


class TestStoryEnd:
    def test_story_finishes_early_fails(self, cfg, monkeypatch) -> None:
        """Board done at ~10s while audio runs ~100s → story_end hard fail."""
        words = [
            {"word": "Alpha", "start": 2.0, "end": 2.4},
            {"word": "Omega", "start": 10.0, "end": 10.5},
            {"word": "continues", "start": 50.0, "end": 50.4},
            {"word": "narrating", "start": 95.0, "end": 95.5},
        ]
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps(
                {
                    "01-x": {
                        "text": "Alpha Omega continues narrating",
                        "words": words,
                        "segments": [{"start": 0.0, "end": 96.0, "text": "x"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_scene_spec(cfg, labels=["Alpha", "Omega"])
        _patch_audio_duration(monkeypatch, 100.0)
        check = Validator(cfg)._check_story_end("01")
        assert not check.passed, check.details
        assert any("early" in d.lower() or "finishes" in d.lower() for d in check.details)

    def test_story_spans_narration_passes(self, cfg, monkeypatch) -> None:
        words = [
            {"word": "Alpha", "start": 2.0, "end": 2.4},
            {"word": "Omega", "start": 80.0, "end": 80.5},
        ]
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps(
                {
                    "01-x": {
                        "text": "Alpha Omega",
                        "words": words,
                        "segments": [{"start": 0.0, "end": 85.0, "text": "x"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_scene_spec(cfg, labels=["Alpha", "Omega"])
        _patch_audio_duration(monkeypatch, 90.0)
        check = Validator(cfg)._check_story_end("01")
        assert check.passed, check.details

    def test_unprobed_audio_duration_fails(self, cfg, monkeypatch) -> None:
        """Probe failure must not fall back to transcript end (hides long audio)."""
        words = [
            {"word": "Alpha", "start": 2.0, "end": 2.4},
            {"word": "Omega", "start": 80.0, "end": 80.5},
        ]
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps(
                {
                    "01-x": {
                        "text": "Alpha Omega",
                        "words": words,
                        "segments": [{"start": 0.0, "end": 85.0, "text": "x"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_scene_spec(cfg, labels=["Alpha", "Omega"])
        _patch_audio_duration(monkeypatch, None)
        check = Validator(cfg)._check_story_end("01")
        assert not check.passed
        assert any("cannot probe audio duration" in d for d in check.details)

    def test_story_end_disabled_via_config(self, tmp_path, monkeypatch) -> None:
        raw = {
            "segments": {"default": ["01"], "all": ["01"]},
            "segment_names": {"01": "01-x"},
            "visual_map": {"01": {"type": "manim", "class": "XScene"}},
            "validation": {"story_end": {"enabled": False}},
        }
        (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
        for d in ("narration", "audio", "recordings", "animations"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake mp3 bytes")
        check = Validator(cfg)._check_story_end("01")
        assert check.passed
        assert any("disabled" in d for d in check.details)

    def test_story_end_is_hard_fail_in_pre_push(self, cfg, monkeypatch) -> None:
        words = [
            {"word": "Alpha", "start": 2.0, "end": 2.4},
            {"word": "Omega", "start": 10.0, "end": 10.5},
        ]
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps(
                {
                    "01-x": {
                        "text": "Alpha Omega",
                        "words": words,
                        "segments": [{"start": 0.0, "end": 100.0, "text": "x"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        _write_scene_spec(cfg, labels=["Alpha", "Omega"])
        _patch_audio_duration(monkeypatch, 100.0)
        # timing_sync would also fail if transcript ends early — keep transcript end close
        # to audio so only story_end trips.
        block = json.loads((cfg.animations_dir / "timing.json").read_text())
        block["01-x"]["words"].append({"word": "pad", "start": 98.0, "end": 99.0})
        block["01-x"]["segments"] = [{"start": 0.0, "end": 99.0, "text": "x"}]
        (cfg.animations_dir / "timing.json").write_text(json.dumps(block), encoding="utf-8")
        v = Validator(cfg)
        # Avoid unrelated hard fails from missing recording.
        monkeypatch.setattr(v, "_find_recording", lambda seg: None)
        with pytest.raises(SystemExit):
            v.run_pre_push()


class TestAvSyncCheckWiring:
    def test_av_sync_skips_for_non_manim_type(self, tmp_path) -> None:
        cfg = _bundle(tmp_path, visual_type="still")
        check = Validator(cfg)._check_av_sync("01", tmp_path / "rec.mp4")
        assert check.passed
        assert any("not checked" in d for d in check.details)

    def test_av_sync_disabled_via_config(self, tmp_path) -> None:
        raw = {
            "segments": {"all": ["01"]},
            "segment_names": {"01": "01-x"},
            "visual_map": {"01": {"type": "manim"}},
            "validation": {"av_sync": {"enabled": False}},
        }
        (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        check = Validator(cfg)._check_av_sync("01", tmp_path / "rec.mp4")
        assert check.passed
        assert any("disabled" in d for d in check.details)

    def test_av_sync_anchors_prefer_scene_spec_labels(self, cfg) -> None:
        from docgen.av_sync import AVSyncValidator

        words = [
            {"word": "unrelatedlongword", "start": 1.0, "end": 1.5},
            {"word": "Flask", "start": 5.0, "end": 5.3},
            {"word": "orchestrator", "start": 12.0, "end": 12.6},
            {"word": "anotherlongtoken", "start": 20.0, "end": 20.5},
        ]
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps({"01-x": {"words": words}}), encoding="utf-8"
        )
        _write_scene_spec(cfg, labels=["Flask", "orchestrator"])
        anchors = AVSyncValidator(cfg)._get_anchors("01", {"words": words})
        keys = [a.keyword.lower() for a in anchors]
        assert "flask" in keys or "orchestrator" in keys
        assert "unrelatedlongword" not in keys
        assert "anotherlongtoken" not in keys

    def test_unreadable_scene_spec_fails_get_anchors(self, cfg) -> None:
        from docgen.av_sync import AVSyncValidator

        words = [
            {"word": "unrelatedlongword", "start": 1.0, "end": 1.5},
            {"word": "Flask", "start": 5.0, "end": 5.3},
        ]
        specs = cfg.animations_dir / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        (specs / "01-x.scene.yaml").write_text("{not yaml", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot load scene spec 01-x.scene.yaml"):
            AVSyncValidator(cfg)._get_anchors("01", {"words": words})

    def test_unreadable_scene_spec_fails_av_sync_check(self, cfg, monkeypatch) -> None:
        words = [
            {"word": "unrelatedlongword", "start": 1.0, "end": 1.5},
            {"word": "Flask", "start": 5.0, "end": 5.3},
        ]
        (cfg.animations_dir / "timing.json").write_text(
            json.dumps({"01-x": {"words": words}}), encoding="utf-8"
        )
        specs = cfg.animations_dir / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        (specs / "01-x.scene.yaml").write_text("{not yaml", encoding="utf-8")
        rec = cfg.recordings_dir / "01-x.mp4"
        rec.write_bytes(b"not a video")

        pt = types.ModuleType("pytesseract")
        pt.get_tesseract_version = lambda: "5.0.0"
        monkeypatch.setitem(sys.modules, "pytesseract", pt)

        check = Validator(cfg)._check_av_sync("01", rec)
        assert not check.passed
        assert any("Cannot load scene spec" in d for d in check.details)
        assert any("AV sync check error" in d for d in check.details)


def test_narration_lint_fails_when_file_missing(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    check = Validator(cfg)._check_narration_lint("01")
    assert not check.passed
    assert any("No narration file" in d for d in check.details)


def test_narration_lint_fails_when_file_empty(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    (cfg.narration_dir / "01-x.md").write_text("\n", encoding="utf-8")
    check = Validator(cfg)._check_narration_lint("01")
    assert not check.passed
    assert any("empty after markdown stripping" in d for d in check.details)


def test_story_end_fails_when_paced_spec_has_no_timing_words(cfg) -> None:
    _write_scene_spec(cfg, labels=["Alpha"])
    check = Validator(cfg)._check_story_end("01")
    assert not check.passed, check.details
    assert any("timestamps" in d.lower() or "paced" in d.lower() for d in check.details)


def test_story_end_allows_pace_none_without_words(cfg) -> None:
    specs = cfg.animations_dir / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    raw = {
        "segment_id": "01",
        "class_name": "XScene",
        "title": {"text": "T", "font_size": 36, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 1.0,
                "boxes": [
                    {
                        "label": "Decor",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 1.0,
                        "font_size": 18,
                        "pace": "none",
                    }
                ],
            }
        ],
    }
    (specs / "01-x.scene.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    check = Validator(cfg)._check_story_end("01")
    assert check.passed, check.details


class TestLayoutCheckErrors:
    """Layout OCR crashes must fail the check, not skip as success."""

    def _fake_tesseract(self, monkeypatch, *, installed: bool) -> None:
        pt = types.ModuleType("pytesseract")
        if installed:
            pt.get_tesseract_version = lambda: "5.0.0"
        else:
            def _missing() -> str:
                raise RuntimeError("tesseract is not installed")

            pt.get_tesseract_version = _missing
        monkeypatch.setitem(sys.modules, "pytesseract", pt)

    def test_unexpected_error_fails(self, cfg, monkeypatch) -> None:
        rec = cfg.recordings_dir / "01-x.mp4"
        rec.write_bytes(b"not a video")
        self._fake_tesseract(monkeypatch, installed=True)

        class Boom:
            def __init__(self, _config: Config) -> None:
                pass

            def validate_video(self, _path: Path) -> None:
                raise TypeError("conf is not int")

        monkeypatch.setattr("docgen.manim_layout.LayoutValidator", Boom)
        check = Validator(cfg)._check_layout(rec)
        assert not check.passed
        assert any("Layout check error" in d for d in check.details)
        assert any("conf is not int" in d for d in check.details)
        assert not any("(skipped)" in d for d in check.details)

    def test_tesseract_missing_fails(self, cfg, monkeypatch) -> None:
        rec = cfg.recordings_dir / "01-x.mp4"
        rec.write_bytes(b"not a video")
        self._fake_tesseract(monkeypatch, installed=False)
        check = Validator(cfg)._check_layout(rec)
        assert check.passed is False
        assert any("tesseract unavailable" in d for d in check.details)
        assert not any("skipped" in d.lower() for d in check.details)

    def test_failed_report_still_fails(self, cfg, monkeypatch) -> None:
        from docgen.manim_layout import LayoutIssue, LayoutReport

        rec = cfg.recordings_dir / "01-x.mp4"
        rec.write_bytes(b"not a video")
        self._fake_tesseract(monkeypatch, installed=True)

        class Fail:
            def __init__(self, _config: Config) -> None:
                pass

            def validate_video(self, path: Path) -> LayoutReport:
                return LayoutReport(
                    path=str(path),
                    passed=False,
                    issues=[LayoutIssue(1.5, "overlap", "boxes overlap")],
                )

        monkeypatch.setattr("docgen.manim_layout.LayoutValidator", Fail)
        check = Validator(cfg)._check_layout(rec)
        assert not check.passed
        assert any("overlap" in d for d in check.details)


def _fake_tesseract_missing(monkeypatch, *, mode: str) -> None:
    if mode == "no_module":
        monkeypatch.setitem(sys.modules, "pytesseract", None)
        return

    pt = types.ModuleType("pytesseract")

    def _missing() -> str:
        raise RuntimeError("tesseract is not installed")

    pt.get_tesseract_version = _missing
    monkeypatch.setitem(sys.modules, "pytesseract", pt)


class TestTesseractMissingFails:
    """Missing tesseract must fail OCR / av_sync / layout, not skip-PASS."""

    @pytest.mark.parametrize("check_name", ("ocr_scan", "layout", "av_sync"))
    @pytest.mark.parametrize("mode", ("no_binary", "no_module"))
    def test_tesseract_missing_does_not_skip_pass(
        self, cfg, monkeypatch, check_name: str, mode: str
    ) -> None:
        rec = cfg.recordings_dir / "01-x.mp4"
        rec.write_bytes(b"not a video")
        _fake_tesseract_missing(monkeypatch, mode=mode)
        v = Validator(cfg)
        if check_name == "ocr_scan":
            check = v._check_ocr(rec, [])
        elif check_name == "layout":
            check = v._check_layout(rec)
        else:
            check = v._check_av_sync("01", rec)
        assert check.name == check_name
        assert check.passed is False
        assert any("tesseract unavailable" in d for d in check.details)
        assert not any("skipped" in d.lower() for d in check.details)
