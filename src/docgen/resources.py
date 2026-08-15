"""Resolve packaged files in a source install and in a PyInstaller freeze.

Frozen apps unpack data under ``sys._MEIPASS/docgen/``. Editable / wheel
installs keep templates, static assets, and benchmark JSON next to this file.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def meipass_dir() -> Path | None:
    if not is_frozen():
        return None
    return Path(sys._MEIPASS)


def package_root() -> Path:
    """Directory that contains ``templates/``, ``static/``, ``benchmark_data/``."""
    root = meipass_dir()
    if root is not None:
        bundled = root / "docgen"
        if bundled.is_dir():
            return bundled
        return root
    return Path(__file__).resolve().parent


def static_dir() -> Path:
    return package_root() / "static"


def templates_dir() -> Path:
    return package_root() / "templates"


def benchmark_data_dir() -> Path:
    return package_root() / "benchmark_data"
