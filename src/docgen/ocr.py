"""OCR-based video frame scanning using OpenCV + pytesseract."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class OCRFrame:
    timestamp_sec: float
    text: str
    issues: list[str] = field(default_factory=list)
    boxes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OCRReport:
    path: str
    frames: list[OCRFrame] = field(default_factory=list)
    passed: bool = True


class OCRScanner:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.ocr_cfg = config.ocr_config

    def scan_video(self, video_path: str | Path) -> OCRReport:
        import cv2
        import pytesseract

        video_path = Path(video_path)
        report = OCRReport(path=str(video_path))

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            report.passed = False
            report.frames.append(OCRFrame(0, "", issues=["Could not open video"]))
            return report

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        interval = self.ocr_cfg.get("sample_interval_sec", 2)
        error_patterns = self.ocr_cfg.get("error_patterns", [])
        min_conf = self.ocr_cfg.get("min_confidence", 40)

        timestamps = [0.0]
        t = interval
        while t < duration:
            timestamps.append(t)
            t += interval
        if duration > 0 and timestamps[-1] < duration - 0.5:
            timestamps.append(duration - 0.1)

        for ts in timestamps:
            frame_num = int(ts * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            text = pytesseract.image_to_string(thresh)
            data = pytesseract.image_to_data(thresh, output_type=pytesseract.Output.DICT)

            issues: list[str] = []
            boxes: list[dict[str, Any]] = []

            # Check for error patterns in extracted text
            for pat in error_patterns:
                if re.search(pat, text, re.IGNORECASE):
                    issues.append(f"Error pattern '{pat}' found at {ts:.1f}s")
                    report.passed = False

            # Check for low-confidence regions (garbled text)
            for j, conf in enumerate(data.get("conf", [])):
                try:
                    c = int(conf)
                except (ValueError, TypeError):
                    continue
                word = data["text"][j].strip()
                if not word:
                    continue
                box = {
                    "x": data["left"][j], "y": data["top"][j],
                    "w": data["width"][j], "h": data["height"][j],
                    "text": word, "conf": c,
                }
                boxes.append(box)
                if c < min_conf and len(word) > 2:
                    issues.append(f"Low confidence ({c}%) text '{word}' at {ts:.1f}s")

            report.frames.append(OCRFrame(timestamp_sec=ts, text=text, issues=issues, boxes=boxes))

        cap.release()
        return report
