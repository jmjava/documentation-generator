"""Tests for docgen.pages HTML generation helpers."""

from docgen.pages import _esc


def test_esc_ampersand():
    assert _esc("A & B") == "A &amp; B"


def test_esc_angle_brackets():
    assert _esc("<script>") == "&lt;script&gt;"


def test_esc_quotes():
    assert _esc('say "hello"') == "say &quot;hello&quot;"


def test_esc_clean():
    assert _esc("Normal text") == "Normal text"
