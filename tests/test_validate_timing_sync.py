"""Tests for the ``timing_sync`` validation check (audio ↔ timing.json staleness)."""

from __future__ import annotations

import json
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


def _patch_audio_duration(monkeypatch, seconds: float) -> None:
    monkeypatch.setattr(
        Validator, "_probe_media_duration", staticmethod(lambda p: seconds)
    )


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = _bundle(tmp_path)
    (c.audio_dir / "01-x.mp3").write_bytes(b"fake mp3 bytes")
    return c


class TestTimingSync:
    def test_fresh_timing_passes(self, cfg, monkeypatch) -> None:
        _write_timing(cfg, last_end=10.0)
        _patch_audio_duration(monkeypatch, 10.4)
        check = Validator(cfg)._check_timing_sync("01")
        assert check.passed, check.details

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
