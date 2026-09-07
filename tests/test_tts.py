"""Tests for docgen.tts markdown stripping and duration change detection."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from docgen.config import Config
from docgen.tts import TTSError, TTSGenerator, _probe_duration, markdown_to_tts_plain


def test_strip_headings():
    assert "# Heading" not in markdown_to_tts_plain("# Heading\nSome text")
    assert "Some text" in markdown_to_tts_plain("# Heading\nSome text")


def test_strip_bold():
    assert markdown_to_tts_plain("This is **bold** text") == "This is bold text"


def test_strip_links():
    assert markdown_to_tts_plain("[click here](http://x.com)") == "click here"


def test_strip_code():
    assert markdown_to_tts_plain("Use `kubectl` command") == "Use kubectl command"


def test_strip_metadata():
    text = "target duration: 2 minutes\nActual narration here."
    result = markdown_to_tts_plain(text)
    assert "target duration" not in result
    assert "Actual narration here." in result


def test_strip_stage_directions():
    text = "*(pause)*\nContinue speaking."
    result = markdown_to_tts_plain(text)
    assert "pause" not in result
    assert "Continue speaking." in result


def test_strip_horizontal_rules():
    text = "Before\n---\nAfter"
    result = markdown_to_tts_plain(text)
    assert "---" not in result
    assert "Before" in result
    assert "After" in result


def test_passthrough_plain():
    text = "This is a normal sentence about Tekton pipelines."
    assert markdown_to_tts_plain(text) == text


def test_tts_missing_narration_raises(tmp_path: Path) -> None:
    raw = {
        "dirs": {"narration": "narration", "audio": "audio"},
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-intro"},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "narration").mkdir()
    cfg = Config.from_yaml(p)
    with pytest.raises(TTSError, match="No narration file"):
        TTSGenerator(cfg).generate(segment="01", dry_run=True)


def test_tts_pre_lint_blocks_generate(tmp_path: Path) -> None:
    raw = {
        "dirs": {"narration": "narration", "audio": "audio"},
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-intro"},
        "validation": {"narration_lint": {"block_tts_on_pre_lint": True}},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    narr = tmp_path / "narration"
    narr.mkdir()
    (narr / "01-intro.md").write_text("# Heading\nSpoken line.\n", encoding="utf-8")
    cfg = Config.from_yaml(p)
    with pytest.raises(TTSError, match="pre-TTS lint"):
        TTSGenerator(cfg).generate(segment="01", dry_run=True)


def test_tts_finds_named_stem_not_substring_id(tmp_path: Path) -> None:
    raw = {
        "dirs": {"narration": "narration", "audio": "audio"},
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-intro"},
        "validation": {"narration_lint": {"block_tts_on_pre_lint": False}},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    narr = tmp_path / "narration"
    narr.mkdir()
    (narr / "101-other.md").write_text("Wrong file.\n", encoding="utf-8")
    (narr / "01-intro.md").write_text("Correct spoken line.\n", encoding="utf-8")
    cfg = Config.from_yaml(p)
    TTSGenerator(cfg).generate(segment="01", dry_run=True)


def test_probe_duration_returns_none_for_missing_file(tmp_path):
    result = _probe_duration(tmp_path / "nonexistent.mp3")
    assert result is None


@patch("docgen.tts.subprocess.run")
def test_probe_duration_returns_float(mock_run):
    mock_run.return_value = type("R", (), {"stdout": "12.345\n"})()
    result = _probe_duration(__import__("pathlib").Path("/tmp/test.mp3"))
    assert result == 12.345
