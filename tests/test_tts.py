"""Tests for docgen.tts markdown stripping and duration change detection."""

from unittest.mock import patch

from docgen.tts import _probe_duration, markdown_to_tts_plain


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


def test_probe_duration_returns_none_for_missing_file(tmp_path):
    result = _probe_duration(tmp_path / "nonexistent.mp3")
    assert result is None


@patch("docgen.tts.subprocess.run")
def test_probe_duration_returns_float(mock_run):
    mock_run.return_value = type("R", (), {"stdout": "12.345\n"})()
    result = _probe_duration(__import__("pathlib").Path("/tmp/test.mp3"))
    assert result == 12.345
