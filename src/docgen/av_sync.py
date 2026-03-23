"""Audio-visual synchronization validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class SyncAnchor:
    keyword: str
    spoken_at: float
    visible: bool = False
    frame_text: str = ""


@dataclass
class AVSyncReport:
    segment: str
    anchors: list[SyncAnchor] = field(default_factory=list)
    passed: bool = True


class AVSyncValidator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.sync_cfg = config.av_sync_config

    def validate_segment(
        self, seg_id: str, video_path: str | Path, audio_path: str | Path
    ) -> AVSyncReport:
        if not self.sync_cfg.get("enabled", True):
            return AVSyncReport(segment=seg_id)

        import cv2
        import pytesseract

        from docgen.timestamps import TimestampExtractor

        report = AVSyncReport(segment=seg_id)
        tolerance = self.sync_cfg.get("tolerance_sec", 3.0)

        # Get transcript with timestamps
        extractor = TimestampExtractor(self.config)
        ts_data = extractor.extract(str(audio_path))

        # Extract anchor keywords from configured or auto-detect
        anchors = self._get_anchors(seg_id, ts_data)
        if not anchors:
            return report

        # Open video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            report.passed = False
            return report
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        for anchor in anchors:
            # Sample frames within tolerance window
            start_t = max(0, anchor.spoken_at - tolerance)
            end_t = anchor.spoken_at + tolerance
            found = False

            for t in [anchor.spoken_at, start_t, end_t,
                       anchor.spoken_at - tolerance / 2, anchor.spoken_at + tolerance / 2]:
                frame_num = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                text = pytesseract.image_to_string(gray).lower()
                if anchor.keyword.lower() in text:
                    anchor.visible = True
                    anchor.frame_text = text[:200]
                    found = True
                    break

            if not found:
                anchor.visible = False
                report.passed = False

            report.anchors.append(anchor)

        cap.release()
        return report

    def _get_anchors(self, seg_id: str, ts_data: dict[str, Any]) -> list[SyncAnchor]:
        # Check for configured anchors
        configured = self.sync_cfg.get("anchor_keywords", {}).get(seg_id, [])
        if configured:
            return [
                SyncAnchor(keyword=a["keyword"], spoken_at=a["expected_at"])
                for a in configured
            ]

        # Auto-extract: nouns from transcript words that are >5 chars
        words = ts_data.get("words", [])
        seen: set[str] = set()
        anchors: list[SyncAnchor] = []
        min_anchors = self.sync_cfg.get("min_anchors_per_segment", 2)

        for w in words:
            word = re.sub(r"[^a-zA-Z]", "", w.get("word", ""))
            if len(word) > 5 and word.lower() not in seen:
                seen.add(word.lower())
                anchors.append(SyncAnchor(keyword=word, spoken_at=w.get("start", 0)))
                if len(anchors) >= min_anchors * 2:
                    break

        return anchors[:max(min_anchors, 3)]
