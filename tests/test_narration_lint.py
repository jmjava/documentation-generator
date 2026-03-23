"""Tests for docgen.narration_lint."""

from docgen.narration_lint import lint_pre_tts, lint_post_tts


def test_pre_tts_clean():
    result = lint_pre_tts("This is a clean narration about Tekton pipelines.")
    assert result.passed


def test_pre_tts_target_duration():
    result = lint_pre_tts("target duration: 2 minutes\nSome narration.")
    assert not result.passed
    assert any("target duration" in i for i in result.issues)


def test_pre_tts_heading():
    result = lint_pre_tts("# Architecture\nThe system does X.")
    assert not result.passed
    assert any("heading" in i.lower() for i in result.issues)


def test_pre_tts_bold_markdown():
    result = lint_pre_tts("This has **bold** text that TTS should not see.")
    assert not result.passed


def test_pre_tts_link():
    result = lint_pre_tts("See [docs](http://example.com) for more.")
    assert not result.passed


def test_post_tts_clean():
    result = lint_post_tts("Welcome to tekton dag a stack aware CI CD system.")
    assert result.passed


def test_post_tts_artifact():
    result = lint_post_tts("The target duration for this segment is two minutes.")
    assert not result.passed
    assert any("target duration" in i for i in result.issues)


def test_post_tts_script_section():
    result = lint_post_tts("This is the narration segment about architecture.")
    assert not result.passed


def test_post_tts_custom_patterns():
    result = lint_post_tts("Normal speech here.", deny_patterns=["normal speech"])
    assert not result.passed
