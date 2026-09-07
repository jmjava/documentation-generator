"""Tests for fail-closed concat."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from docgen.concat import ConcatBuilder, ConcatError
from docgen.config import Config, ConfigError


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


def test_concat_string_segment_list_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="concat.full must be a YAML list"):
        _cfg(tmp_path, {"full": "01"})


def test_concat_builder_rejects_non_list_target() -> None:
    from pathlib import Path as P
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        concat_map={"full": "01"},
        recordings_dir=P("/tmp"),
        find_segment_asset=lambda *a, **k: None,
    )
    with pytest.raises(ConcatError, match="must be a YAML list"):
        ConcatBuilder(cfg).build()  # type: ignore[arg-type]


def test_concat_builder_rejects_integer_segment_id() -> None:
    from pathlib import Path as P
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        concat_map={"full": [1]},
        recordings_dir=P("/tmp"),
        find_segment_asset=lambda *a, **k: None,
    )
    with pytest.raises(ConcatError, match="quoted string segment id"):
        ConcatBuilder(cfg).build()  # type: ignore[arg-type]


def _seed_recordings(tmp_path: Path) -> None:
    rec = tmp_path / "recordings"
    rec.mkdir()
    (rec / "01-a.mp4").write_bytes(b"seg-a")
    (rec / "02-b.mp4").write_bytes(b"seg-b")


def test_concat_ffmpeg_timeout_removes_incomplete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path, {"full": ["01", "02"]})
    _seed_recordings(tmp_path)
    out = tmp_path / "recordings" / "full.mp4"
    out.write_bytes(b"partial-concat")

    def fake_run(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ConcatError, match="removed incomplete full.mp4"):
        ConcatBuilder(cfg).build(name="full")
    assert not out.exists()
    assert not list((tmp_path / "recordings").glob(".concat-*.txt"))


def test_concat_ffmpeg_failure_removes_incomplete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path, {"full": ["01", "02"]})
    _seed_recordings(tmp_path)
    out = tmp_path / "recordings" / "full.mp4"
    out.write_bytes(b"partial-concat")

    def fake_run(cmd, **_kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="mux error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ConcatError, match="ffmpeg failed"):
        ConcatBuilder(cfg).build(name="full")
    assert not out.exists()
