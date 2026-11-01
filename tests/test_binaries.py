"""Configured binaries must not silently fall back to a different executable."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from docgen.binaries import resolve_binary


def _executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)


def test_configured_path_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "configured-manim"
    decoy = tmp_path / "decoy-manim"
    _executable(decoy)
    monkeypatch.setattr(shutil, "which", lambda _name: str(decoy))
    monkeypatch.setattr(sys, "executable", str(decoy))

    resolution = resolve_binary("manim", configured_path=str(missing))

    assert resolution.path is None
    assert resolution.tried == [str(missing)]


def test_configured_executable_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "real-manim"
    decoy = tmp_path / "other-manim"
    _executable(configured)
    _executable(decoy)
    monkeypatch.setattr(shutil, "which", lambda _name: str(decoy))

    resolution = resolve_binary("manim", configured_path=str(configured))

    assert resolution.path == str(configured)
