"""Extended tests for Manim layout/contrast validation."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import yaml

from docgen.config import Config
from docgen.manim_layout import LayoutValidator


def _write_cfg(tmp_path: Path, validation_cfg: dict | None = None) -> Config:
    cfg = {
        "dirs": {"recordings": "recordings"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "source": "01-demo.mp4"}},
        "validation": validation_cfg or {},
    }
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(path)


def _write_video(path: Path, frames: list[np.ndarray], fps: int = 10) -> None:
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for frame in frames:
        writer.write(frame)
    writer.release()


def _dark_bg_with_text(
    text: str,
    *,
    width: int = 640,
    height: int = 360,
    pos: tuple[int, int] = (30, 180),
    color: tuple[int, int, int] = (235, 235, 235),
    bg: int = 20,
    scale: float = 0.9,
    thickness: int = 2,
) -> np.ndarray:
    frame = np.full((height, width, 3), bg, dtype=np.uint8)
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)
    return frame


def test_layout_passes_or_skips_when_tesseract_missing(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path)
    validator = LayoutValidator(cfg)
    video = tmp_path / "recordings" / "01-demo.mp4"
    frames = [_dark_bg_with_text("Centered clear text", pos=(120, 180)) for _ in range(40)]
    _write_video(video, frames)

    report = validator.validate_video(video)
    if any("tesseract unavailable" in i.description for i in report.issues):
        assert report.passed
        return
    assert report.passed, [i.description for i in report.issues]


def test_layout_detects_edge_clipping_when_available(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, {"layout": {"edge_margin_px": 30}})
    validator = LayoutValidator(cfg)
    video = tmp_path / "recordings" / "01-demo.mp4"
    # Start text near left edge to trigger safe-zone violation.
    frames = [_dark_bg_with_text("Too close edge", pos=(2, 180)) for _ in range(30)]
    _write_video(video, frames)

    report = validator.validate_video(video)
    if any("tesseract unavailable" in i.description for i in report.issues):
        assert report.passed
        return
    assert not report.passed
    assert any(issue.kind == "edge" for issue in report.issues)


def test_layout_detects_low_contrast_when_available(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, {"layout": {"min_contrast_ratio": 4.5}})
    validator = LayoutValidator(cfg)
    video = tmp_path / "recordings" / "01-demo.mp4"
    # Light gray text on slightly lighter gray background => poor contrast.
    frames = [
        _dark_bg_with_text(
            "Low contrast text",
            pos=(120, 180),
            color=(120, 120, 120),
            bg=90,
            thickness=2,
        )
        for _ in range(30)
    ]
    _write_video(video, frames)

    report = validator.validate_video(video)
    if any("tesseract unavailable" in i.description for i in report.issues):
        assert report.passed
        return
    assert not report.passed
    assert any(issue.kind == "contrast" for issue in report.issues)


def test_layout_detects_tiny_text_when_available(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, {"layout": {"min_text_height_px": 12}})
    validator = LayoutValidator(cfg)
    video = tmp_path / "recordings" / "01-demo.mp4"
    frames = [
        _dark_bg_with_text(
            "tiny text",
            pos=(220, 180),
            scale=0.35,
            thickness=1,
        )
        for _ in range(30)
    ]
    _write_video(video, frames)

    report = validator.validate_video(video)
    if any("tesseract unavailable" in i.description for i in report.issues):
        assert report.passed
        return
    assert not report.passed
    assert any(issue.kind == "readability" for issue in report.issues)
