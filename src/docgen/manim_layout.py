"""Layout validation for Manim frames: overlap, spacing, edge clipping."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
        import pytesseract

        video_path = Path(video_path)
        report = LayoutReport(path=str(video_path))
        min_spacing = self.layout_cfg.get("min_spacing_px", 10)
        edge_margin = self.layout_cfg.get("edge_margin_px", 15)
        check_overlap = self.layout_cfg.get("check_overlap", True)

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

        # Sample: first, middle, last
        timestamps = [0.0]
        if duration > 1:
            timestamps.append(duration / 2)
        if duration > 2:
            timestamps.append(duration - 0.1)

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

            # Edge clipping
            for b in boxes:
                if b["x"] < edge_margin or b["y"] < edge_margin:
                    report.issues.append(LayoutIssue(
                        ts, "edge", f"Text too close to top/left edge at ({b['x']},{b['y']})"
                    ))
                    report.passed = False
                if b["x"] + b["w"] > w_frame - edge_margin:
                    report.issues.append(LayoutIssue(
                        ts, "edge", f"Text too close to right edge at x={b['x']+b['w']}"
                    ))
                    report.passed = False
                if b["y"] + b["h"] > h_frame - edge_margin:
                    report.issues.append(LayoutIssue(
                        ts, "edge", f"Text too close to bottom edge at y={b['y']+b['h']}"
                    ))
                    report.passed = False

            # Overlap and spacing
            if check_overlap:
                for i in range(len(boxes)):
                    for j in range(i + 1, len(boxes)):
                        a, b_ = boxes[i], boxes[j]
                        if _boxes_overlap(a, b_):
                            report.issues.append(LayoutIssue(
                                ts, "overlap", f"Overlapping text regions at {ts:.1f}s"
                            ))
                            report.passed = False
                        elif _box_distance(a, b_) < min_spacing:
                            report.issues.append(LayoutIssue(
                                ts, "spacing",
                                f"Text regions too close ({_box_distance(a, b_):.0f}px) at {ts:.1f}s"
                            ))
                            report.passed = False

        cap.release()
        return report


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
