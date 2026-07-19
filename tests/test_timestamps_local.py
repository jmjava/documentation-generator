"""Tests for the ``timestamps`` engine selection and local (no-Whisper) extraction."""

from __future__ import annotations

import json

import pytest
import yaml

import docgen.align as align_module
from docgen.config import Config
from docgen.timestamps import TimestampExtractor


@pytest.fixture
def cfg(tmp_path) -> Config:
    raw = {
        "segments": {"all": ["01"]},
        "segment_names": {"01": "01-x"},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "audio").mkdir()
    (tmp_path / "narration").mkdir()
    return Config.from_yaml(tmp_path / "docgen.yaml")


def _fake_audio_env(monkeypatch, duration: float = 6.0) -> None:
    """Bypass ffprobe/ffmpeg: fixed duration, one mid-audio silence."""
    monkeypatch.setattr(align_module, "probe_duration", lambda p: duration)
    monkeypatch.setattr(
        align_module,
        "detect_speech_intervals",
        lambda p, d, **kw: [(0.0, d / 2 - 0.3), (d / 2 + 0.3, d)],
    )


class TestResolveEngine:
    def test_default_is_local(self, cfg) -> None:
        assert TimestampExtractor(cfg).resolve_engine() == "local"

    def test_config_engine_respected(self, tmp_path) -> None:
        (tmp_path / "docgen.yaml").write_text(
            yaml.dump({"timestamps": {"engine": "whisper"}}), encoding="utf-8"
        )
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        assert TimestampExtractor(cfg).resolve_engine() == "whisper"

    def test_cli_override_wins(self, cfg) -> None:
        assert TimestampExtractor(cfg).resolve_engine("whisper") == "whisper"

    def test_unknown_engine_fails_loud(self, cfg) -> None:
        with pytest.raises(RuntimeError, match="unknown engine"):
            TimestampExtractor(cfg).resolve_engine("gibberish")


class TestExtractLocal:
    def test_writes_whisper_shaped_timing_json(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text(
            "# Heading\n\nAlpha begins the story. Beta ends it.\n", encoding="utf-8"
        )
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")

        TimestampExtractor(cfg).extract_all()

        timing = json.loads((cfg.animations_dir / "timing.json").read_text(encoding="utf-8"))
        block = timing["01-x"]
        assert set(block.keys()) == {"text", "segments", "words"}
        assert [s["text"] for s in block["segments"]] == [
            "Alpha begins the story.",
            "Beta ends it.",
        ]
        # Two sentences, two detected speech intervals → 1:1 mapping.
        assert block["segments"][1]["start"] == pytest.approx(3.3)
        assert block["words"][0]["word"] == "Alpha"

    def test_missing_narration_fails_loud(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        with pytest.raises(RuntimeError, match="narration/01-x.md"):
            TimestampExtractor(cfg).extract_all()

    def test_markdown_is_stripped_before_alignment(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text(
            "# Title skipped\n\n**Bold** words spoken here. Second `code` sentence.\n",
            encoding="utf-8",
        )
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")

        TimestampExtractor(cfg).extract_all()

        timing = json.loads((cfg.animations_dir / "timing.json").read_text(encoding="utf-8"))
        words = [w["word"] for w in timing["01-x"]["words"]]
        assert "Bold" in words
        assert "#" not in " ".join(words)
        assert "**Bold**" not in words
