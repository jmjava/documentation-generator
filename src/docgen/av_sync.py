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


def _ocr_keyword_from_label(label: str) -> str | None:
    """Pick a distinctive token from a scene-spec label for OCR substring match."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", label or "")
    if not tokens:
        return None
    # Prefer longer tokens (OCR noise is worse on short words).
    return max(tokens, key=len)


class AVSyncValidator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.sync_cfg = config.av_sync_config

    def validate_segment(
        self, seg_id: str, video_path: str | Path, audio_path: str | Path
    ) -> AVSyncReport:
        """Transcribe ``audio_path`` via Whisper (network call), then anchor-check.

        Prefer :meth:`validate_segment_with_timing` with data from the bundle's
        ``timing.json`` so validation stays offline.
        """
        if not self.sync_cfg.get("enabled", True):
            return AVSyncReport(segment=seg_id)

        from docgen.timestamps import TimestampExtractor

        extractor = TimestampExtractor(self.config)
        ts_data = extractor.extract(str(audio_path))
        return self.validate_segment_with_timing(seg_id, video_path, ts_data)

    def validate_segment_with_timing(
        self, seg_id: str, video_path: str | Path, ts_data: dict[str, Any]
    ) -> AVSyncReport:
        """OCR-check that spoken anchor keywords appear on screen near their spoken time.

        ``ts_data`` is one segment's block from ``timing.json`` (``words`` list
        with ``word``/``start``). No network calls.
        """
        if not self.sync_cfg.get("enabled", True):
            return AVSyncReport(segment=seg_id)

        import cv2
        import pytesseract

        report = AVSyncReport(segment=seg_id)
        tolerance = self.sync_cfg.get("tolerance_sec", 3.0)

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

        words = ts_data.get("words", [])
        if not isinstance(words, list):
            words = []

        if self.sync_cfg.get("prefer_scene_spec_labels", True):
            from_spec = self._anchors_from_scene_specs(seg_id, words)
            if from_spec:
                return from_spec

        # Fallback: nouns from transcript words that are >5 chars
        seen: set[str] = set()
        anchors: list[SyncAnchor] = []
        min_anchors = int(self.sync_cfg.get("min_anchors_per_segment", 2))

        for w in words:
            if not isinstance(w, dict):
                continue
            word = re.sub(r"[^a-zA-Z]", "", w.get("word", ""))
            if len(word) > 5 and word.lower() not in seen:
                seen.add(word.lower())
                anchors.append(SyncAnchor(keyword=word, spoken_at=w.get("start", 0)))
                if len(anchors) >= min_anchors * 2:
                    break

        return anchors[: max(min_anchors, 3)]

    def _anchors_from_scene_specs(
        self, seg_id: str, words: list[Any]
    ) -> list[SyncAnchor]:
        """Build OCR anchors from paced scene-spec labels (on-screen text)."""
        if not words:
            return []

        from docgen.scene_retime import list_scene_spec_paths
        from docgen.scene_spec import iter_paced_label_anchors, load_scene_spec

        paths = list_scene_spec_paths(self.config, segment_id=seg_id)
        if not paths:
            return []

        min_anchors = int(self.sync_cfg.get("min_anchors_per_segment", 2))
        max_anchors = int(self.sync_cfg.get("max_anchors_per_segment", 8))
        max_anchors = max(min_anchors, max_anchors)

        seen: set[str] = set()
        anchors: list[SyncAnchor] = []
        word_dicts = [w for w in words if isinstance(w, dict)]

        for path in paths:
            try:
                spec = load_scene_spec(path)
            except Exception:
                continue
            for label, spoken_at in iter_paced_label_anchors(spec, word_dicts):
                keyword = _ocr_keyword_from_label(label)
                if not keyword or keyword.lower() in seen:
                    continue
                seen.add(keyword.lower())
                anchors.append(SyncAnchor(keyword=keyword, spoken_at=spoken_at))
                if len(anchors) >= max_anchors:
                    return anchors
        return anchors
