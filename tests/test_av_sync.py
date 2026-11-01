"""AV sync must not invent a frame rate when the video does not report one."""

from __future__ import annotations

from pathlib import Path

import cv2
import pytest
import yaml

from docgen.av_sync import AVSyncValidator
from docgen.config import Config


def _cfg(tmp_path: Path) -> Config:
    raw = {"segments": {"all": ["01"], "default": ["01"]}}
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(path)


class _Cap:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.fps = 0.0
        self.sampled = False

    def isOpened(self) -> bool:
        return True

    def get(self, _prop: int) -> float:
        return self.fps

    def set(self, *_args: object) -> None:
        self.sampled = True

    def read(self) -> tuple[bool, None]:
        self.sampled = True
        return False, None

    def release(self) -> None:
        return None


def test_zero_fps_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Cap()
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_a, **_k: cap)
    words = {"words": [{"word": "pipeline", "start": 1.0}, {"word": "checkout", "start": 2.0}]}
    with pytest.raises(ValueError, match="positive finite"):
        AVSyncValidator(_cfg(tmp_path)).validate_segment_with_timing("01", tmp_path / "clip.mp4", words)
    assert cap.sampled is False


def test_positive_fps_still_samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Cap()
    cap.fps = 30.0
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_a, **_k: cap)
    words = {"words": [{"word": "pipeline", "start": 1.0}, {"word": "checkout", "start": 2.0}]}
    report = AVSyncValidator(_cfg(tmp_path)).validate_segment_with_timing(
        "01", tmp_path / "clip.mp4", words
    )
    assert cap.sampled is True
    assert report.passed is False
