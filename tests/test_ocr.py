"""OCR scanning must not invent a frame rate when the video does not report one."""

from __future__ import annotations

from pathlib import Path

import cv2
import pytest
import yaml

from docgen.config import Config
from docgen.ocr import OCRScanner


def _cfg(tmp_path: Path) -> Config:
    raw = {"segments": {"all": ["01"], "default": ["01"]}}
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(path)


class _Cap:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.fps = 0.0
        self.frames = 0.0
        self.sampled = False

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return self.frames
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
    with pytest.raises(ValueError, match="positive finite"):
        OCRScanner(_cfg(tmp_path)).scan_video(tmp_path / "clip.mp4")
    assert cap.sampled is False


def test_zero_sample_interval_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = {
        "segments": {"all": ["01"], "default": ["01"]},
        "validation": {"ocr": {"sample_interval_sec": 0}},
    }
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(raw), encoding="utf-8")
    cap = _Cap()
    cap.fps = 30.0
    cap.frames = 0.0
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_a, **_k: cap)
    with pytest.raises(ValueError, match="sample interval"):
        OCRScanner(Config.from_yaml(path)).scan_video(tmp_path / "clip.mp4")
    assert cap.sampled is False


def test_positive_fps_still_samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _Cap()
    cap.fps = 30.0
    cap.frames = 30.0
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_a, **_k: cap)
    report = OCRScanner(_cfg(tmp_path)).scan_video(tmp_path / "clip.mp4")
    assert cap.sampled is True
    assert report.passed is True
