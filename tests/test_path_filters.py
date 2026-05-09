"""Tests for docgen.path_filters."""

from docgen.path_filters import is_under_archive_dir


def test_archive_component_detected_mid_path():
    assert is_under_archive_dir("docs/archive/old/README.md") is True


def test_archive_as_repo_root_segment():
    assert is_under_archive_dir("archive/notes.md") is True


def test_no_false_positive_on_filename():
    assert is_under_archive_dir("src/not_archive/foo.md") is False


def test_windows_separators_normalized():
    assert is_under_archive_dir("docs\\archive\\x.md") is True
