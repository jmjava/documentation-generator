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


def _append_candidate(candidates: list[str], candidate: str | Path | None) -> None:
    if not candidate:
        return
    expanded = os.path.expanduser(os.path.expandvars(str(candidate).strip()))
    if expanded and expanded not in candidates:
        candidates.append(expanded)


def _pinned_binary(configured_path: str | None) -> str | None:
    """A configured path is the only candidate; blank means discovery is allowed."""
    if configured_path is None:
        return None
    expanded = os.path.expanduser(os.path.expandvars(str(configured_path).strip()))
    if not expanded:
        return None
    return expanded


def _fallback_candidates(
    name: str,
    extra_candidates: list[str | Path] | None,
) -> list[str]:
    candidates: list[str] = []
    _append_candidate(candidates, Path(sys.executable).resolve().parent / name)
    for candidate in extra_candidates or []:
        _append_candidate(candidates, candidate)
    _append_candidate(candidates, shutil.which(name))
    return candidates


def _binary_candidates(
    name: str,
    configured_path: str | None,
    extra_candidates: list[str | Path] | None,
) -> list[str]:
    pinned = _pinned_binary(configured_path)
    if pinned is not None:
        return [pinned]
    return _fallback_candidates(name, extra_candidates)


def resolve_binary(
    name: str,
    *,
    configured_path: str | None = None,
    extra_candidates: list[str | Path] | None = None,
) -> BinaryResolution:
    """Resolve an executable. A configured path is never replaced by PATH."""
    tried: list[str] = []
    for candidate in _binary_candidates(name, configured_path, extra_candidates):
        tried.append(candidate)
        cpath = Path(candidate)
        if cpath.exists() and os.access(cpath, os.X_OK):
            return BinaryResolution(name=name, path=str(cpath), tried=tried)

    return BinaryResolution(name=name, path=None, tried=tried)
