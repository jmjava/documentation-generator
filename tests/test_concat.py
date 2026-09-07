"""Tests for fail-closed concat."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docgen.concat import ConcatBuilder, ConcatError
from docgen.config import Config


def _cfg(tmp_path: Path, concat: dict) -> Config:
    raw = {
        "dirs": {"recordings": "recordings"},
        "segments": {"all": ["01", "02"], "default": ["01", "02"]},
        "segment_names": {"01": "01-a", "02": "02-b"},
        "concat": concat,
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(p)


def test_concat_unknown_target_raises(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, {"full": ["01", "02"]})
    with pytest.raises(ConcatError, match="unknown target"):
        ConcatBuilder(cfg).build(name="missing")


def test_concat_missing_recording_raises_before_ffmpeg(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, {"full": ["01", "02"]})
    (tmp_path / "recordings").mkdir()
    (tmp_path / "recordings" / "01-a.mp4").write_bytes(b"x")
    with pytest.raises(ConcatError, match="missing recording"):
        ConcatBuilder(cfg).build(name="full")


def test_concat_empty_map_is_noop(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, {})
    ConcatBuilder(cfg).build()
