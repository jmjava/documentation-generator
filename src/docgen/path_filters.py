"""Shared path filters for repo-wide scans (wizard, test discovery, etc.)."""

from __future__ import annotations

from pathlib import PurePosixPath


def is_under_archive_dir(rel_posix: str) -> bool:
    """True when any path component is exactly ``archive`` (case-sensitive).

    Matches ``legacy/archive/foo.md``, ``docs/archive/``, etc. Used so archived
    material is ignored by default in wizard scans and Playwright discovery
    without requiring every consumer repo to list ``**/archive/**`` in YAML.
    """
    parts = PurePosixPath(rel_posix.replace("\\", "/")).parts
    return "archive" in parts
