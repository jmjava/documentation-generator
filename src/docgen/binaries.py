"""Helpers for resolving external binary paths."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BinaryResolution:
    name: str
    path: str | None
    tried: list[str] = field(default_factory=list)


def resolve_binary(
    name: str,
    *,
    configured_path: str | None = None,
    extra_candidates: list[str | Path] | None = None,
) -> BinaryResolution:
    """Resolve an executable path using config overrides + sensible defaults."""
    candidates: list[str] = []

    def _add(candidate: str | Path | None) -> None:
        if not candidate:
            return
        p = str(candidate).strip()
        if not p:
            return
        p = os.path.expanduser(os.path.expandvars(p))
        if p not in candidates:
            candidates.append(p)

    _add(configured_path)

    # If docgen is running from a virtualenv, prefer binaries next to this python.
    _add(Path(sys.executable).resolve().parent / name)

    for candidate in extra_candidates or []:
        _add(candidate)

    which_hit = shutil.which(name)
    if which_hit:
        _add(which_hit)

    tried: list[str] = []
    for candidate in candidates:
        tried.append(candidate)
        cpath = Path(candidate)
        if cpath.exists() and os.access(cpath, os.X_OK):
            return BinaryResolution(name=name, path=str(cpath), tried=tried)

    return BinaryResolution(name=name, path=None, tried=tried)
