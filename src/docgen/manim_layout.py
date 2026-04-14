"""Layout validation for Manim frames: overlap, spacing, edge clipping, contrast."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class LayoutIssue:
    timestamp_sec: float
    kind: str  # overlap, spacing, edge
    description: str


@dataclass
class LayoutReport:
    path: str
    issues: list[LayoutIssue] = field(default_factory=list)
    passed: bool = True


class LayoutValidator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.layout_cfg = config.layout_config

    def validate_video(self, video_path: str | Path) -> LayoutReport:
        import cv2
        try:
            import pytesseract
            # Validate binary availability up-front.
            pytesseract.get_tesseract_version()
        except Exception:
            video_path = Path(video_path)
            return LayoutReport(
                path=str(video_path),
                issues=[LayoutIssue(0.0, "warning", "tesseract unavailable; layout checks skipped")],
                passed=True,
            )

        video_path = Path(video_path)
        report = LayoutReport(path=str(video_path))
        min_spacing = self.layout_cfg.get("min_spacing_px", 10)
        edge_margin = self.layout_cfg.get("edge_margin_px", 15)
        check_overlap = self.layout_cfg.get("check_overlap", True)
        sample_interval = float(self.layout_cfg.get("sample_interval_sec", 2.0))
        check_contrast = bool(self.layout_cfg.get("check_contrast", True))
        min_contrast_ratio = float(self.layout_cfg.get("min_contrast_ratio", 3.5))
        check_font_size = bool(self.layout_cfg.get("check_font_size", True))
        min_text_height = int(self.layout_cfg.get("min_text_height_px", 10))
        max_text_regions = int(self.layout_cfg.get("max_text_regions", 45))

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            report.passed = False
            report.issues.append(LayoutIssue(0, "error", "Could not open video"))
            return report

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total / fps if fps > 0 else 0
        h_frame = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w_frame = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        timestamps = _sample_timestamps(duration, sample_interval)

        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
            ret, frame = cap.read()
            if not ret:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)

            boxes: list[dict[str, int]] = []
            for i in range(len(data["text"])):
                word = data["text"][i].strip()
                if not word:
                    continue
                try:
                    if int(data["conf"][i]) < 20:
                        continue
                except (ValueError, TypeError):
                    continue
                boxes.append({
                    "x": data["left"][i], "y": data["top"][i],
                    "w": data["width"][i], "h": data["height"][i],
                })

            issues = _analyze_boxes(
                boxes=boxes,
                gray_frame=gray,
                frame_width=w_frame,
                frame_height=h_frame,
                timestamp_sec=ts,
                edge_margin=edge_margin,
                min_spacing=min_spacing,
                check_overlap=check_overlap,
                max_text_regions=max_text_regions,
                check_contrast=check_contrast,
                min_contrast_ratio=min_contrast_ratio,
                check_font_size=check_font_size,
                min_text_height=min_text_height,
            )
            if issues:
                report.passed = False
                report.issues.extend(issues)

        cap.release()
        return report


def _sample_timestamps(duration_sec: float, interval_sec: float) -> list[float]:
    if duration_sec <= 0:
        return [0.0]
    step = max(0.25, float(interval_sec))
    points: list[float] = []
    t = 0.0
    while t < duration_sec:
        points.append(t)
        t += step
    if not points or points[-1] < duration_sec - 0.2:
        points.append(max(0.0, duration_sec - 0.1))
    return points


def _analyze_boxes(
    boxes: list[dict[str, int]],
    gray_frame: Any,
    frame_width: int,
    frame_height: int,
    timestamp_sec: float,
    edge_margin: int,
    min_spacing: int,
    check_overlap: bool,
    max_text_regions: int,
    check_contrast: bool,
    min_contrast_ratio: float,
    check_font_size: bool,
    min_text_height: int,
) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []

    if len(boxes) > max_text_regions:
        issues.append(
            LayoutIssue(
                timestamp_sec,
                "density",
                f"Too many text regions ({len(boxes)} > {max_text_regions})",
            )
        )

    for b in boxes:
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        if x < edge_margin or y < edge_margin:
            issues.append(
                LayoutIssue(timestamp_sec, "edge", f"Text too close to top/left edge at ({x},{y})")
            )
        if x + w > frame_width - edge_margin:
            issues.append(
                LayoutIssue(timestamp_sec, "edge", f"Text too close to right edge at x={x + w}")
            )
        if y + h > frame_height - edge_margin:
            issues.append(
                LayoutIssue(timestamp_sec, "edge", f"Text too close to bottom edge at y={y + h}")
            )
        if check_font_size and h < min_text_height:
            issues.append(
                LayoutIssue(
                    timestamp_sec,
                    "readability",
                    f"Text too small (height={h}px, min={min_text_height}px)",
                )
            )
        if check_contrast:
            contrast = _estimate_box_contrast(gray_frame, b)
            if contrast is not None and contrast < min_contrast_ratio:
                issues.append(
                    LayoutIssue(
                        timestamp_sec,
                        "contrast",
                        f"Low text contrast ({contrast:.2f}:1 < {min_contrast_ratio:.2f}:1)",
                    )
                )

    if check_overlap:
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b_ = boxes[i], boxes[j]
                if _boxes_overlap(a, b_):
                    issues.append(LayoutIssue(timestamp_sec, "overlap", "Overlapping text regions"))
                elif _box_distance(a, b_) < min_spacing:
                    issues.append(
                        LayoutIssue(
                            timestamp_sec,
                            "spacing",
                            f"Text regions too close ({_box_distance(a, b_):.0f}px)",
                        )
                    )
    return issues


def _boxes_overlap(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


def _box_distance(a: dict, b: dict) -> float:
    dx = max(0, max(a["x"], b["x"]) - min(a["x"] + a["w"], b["x"] + b["w"]))
    dy = max(0, max(a["y"], b["y"]) - min(a["y"] + a["h"], b["y"] + b["h"]))
    return (dx * dx + dy * dy) ** 0.5


def _estimate_box_contrast(gray_frame: Any, box: dict[str, int]) -> float | None:
    import cv2
    import numpy as np

    x = max(0, int(box["x"]))
    y = max(0, int(box["y"]))
    w = max(1, int(box["w"]))
    h = max(1, int(box["h"]))
    roi = gray_frame[y:y + h, x:x + w]
    if roi is None or roi.size < 8:
        return None

    _, thresh = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = roi[thresh == 0]
    light = roi[thresh == 255]
    if dark.size == 0 or light.size == 0:
        return None

    # Text usually occupies less area than background in OCR boxes.
    if dark.size <= light.size:
        text_px = dark
        bg_px = light
    else:
        text_px = light
        bg_px = dark

    text_l = float(np.mean(text_px)) / 255.0
    bg_l = float(np.mean(bg_px)) / 255.0
    lighter = max(text_l, bg_l)
    darker = min(text_l, bg_l)
    return (lighter + 0.05) / (darker + 0.05)
