"""Sync narration timing to Playwright browser events.

Analogous to :mod:`docgen.tape_sync` for VHS tapes, this module aligns
narration audio timestamps with browser action events extracted from
Playwright traces.

The core algorithm:
  1. Load events from ``events.json`` (trace extraction) and timing from
     ``timing.json`` (Whisper timestamps).
  2. Match configured *anchors* — pairs of (narration keyword, browser action).
  3. Compute speed adjustment factors per inter-anchor segment so visual
     actions align with spoken narration.
  4. Output ``sync_map.json`` and optionally produce a retimed video.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class AnchorMatch:
    """A matched pair: browser event ↔ narration word."""

    event_idx: int
    event_t: float
    action: str
    selector: str
    narration_t: float
    narration_text: str
    confidence: float = 1.0


@dataclass
class SpeedSegment:
    """A piece-wise speed adjustment for one interval of video."""

    video_start: float
    video_end: float
    narration_start: float
    narration_end: float
    factor: float


@dataclass
class SyncResult:
    """Result of synchronizing one segment."""

    segment: str
    anchors: list[AnchorMatch] = field(default_factory=list)
    speed_segments: list[SpeedSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    strategy: str = "stretch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "strategy": self.strategy,
            "anchors": [
                {
                    "event_idx": a.event_idx,
                    "event_t": round(a.event_t, 3),
                    "action": a.action,
                    "selector": a.selector,
                    "narration_t": round(a.narration_t, 3),
                    "narration_text": a.narration_text,
                    "confidence": round(a.confidence, 2),
                }
                for a in self.anchors
            ],
            "speed_segments": [
                {
                    "video_start": round(s.video_start, 3),
                    "video_end": round(s.video_end, 3),
                    "narration_start": round(s.narration_start, 3),
                    "narration_end": round(s.narration_end, 3),
                    "factor": round(s.factor, 4),
                }
                for s in self.speed_segments
            ],
            "warnings": self.warnings,
        }


class PlaywrightSynchronizer:
    """Align narration timestamps with Playwright browser events."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._pt_cfg = config.playwright_test_config
        self._min_speed = float(self._pt_cfg.get("min_speed_factor", 0.25))
        self._max_speed = float(self._pt_cfg.get("max_speed_factor", 4.0))

    def sync(
        self,
        segment: str | None = None,
        dry_run: bool = False,
    ) -> list[SyncResult]:
        """Sync all (or one) playwright_test segments."""
        timing = self._load_timing_json()
        results: list[SyncResult] = []

        for seg_id, vmap in self.config.visual_map.items():
            if vmap.get("type") != "playwright_test":
                continue
            if segment and seg_id != segment:
                continue

            events = self._load_events(seg_id)
            if not events:
                print(f"[sync-pw] SKIP {seg_id}: no events.json")
                continue

            seg_name = self.config.resolve_segment_name(seg_id)
            timing_entry = timing.get(seg_name) or timing.get(seg_id)
            if not timing_entry:
                print(f"[sync-pw] SKIP {seg_id}: no timing data (run docgen timestamps)")
                continue

            anchors_cfg = vmap.get("events", [])
            strategy = vmap.get("sync_strategy") or self._pt_cfg.get("sync_strategy", "stretch")

            result = self._sync_one(
                seg_id=seg_id,
                events=events,
                timing_entry=timing_entry,
                anchors_cfg=anchors_cfg,
                strategy=strategy,
            )
            self._print_result(result, dry_run)

            if not dry_run:
                self._write_sync_map(seg_id, result)

            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Core sync algorithm
    # ------------------------------------------------------------------

    def _sync_one(
        self,
        seg_id: str,
        events: list[dict[str, Any]],
        timing_entry: dict[str, Any],
        anchors_cfg: list[dict[str, Any]],
        strategy: str,
    ) -> SyncResult:
        result = SyncResult(segment=seg_id, strategy=strategy)
        words = timing_entry.get("words", [])

        matched = self._match_anchors(events, words, anchors_cfg, result)

        if len(matched) < 2:
            result.warnings.append(
                f"Only {len(matched)} anchor(s) matched; "
                "falling back to uniform speed distribution."
            )
            total_narration = self._timing_duration(timing_entry)
            total_video = events[-1]["t"] if events else 0
            if total_video > 0 and total_narration > 0:
                factor = total_narration / total_video
                factor = max(self._min_speed, min(self._max_speed, factor))
                result.speed_segments.append(SpeedSegment(
                    video_start=0.0,
                    video_end=total_video,
                    narration_start=0.0,
                    narration_end=total_narration,
                    factor=factor,
                ))
            return result

        matched.sort(key=lambda a: a.event_t)
        result.anchors = matched
        result.speed_segments = self._compute_speed_segments(matched, events, timing_entry)
        return result

    def _match_anchors(
        self,
        events: list[dict[str, Any]],
        words: list[dict[str, Any]],
        anchors_cfg: list[dict[str, Any]],
        result: SyncResult,
    ) -> list[AnchorMatch]:
        """Match configured anchors to events and narration words."""
        matched: list[AnchorMatch] = []

        if anchors_cfg:
            for anchor in anchors_cfg:
                match = self._match_configured_anchor(anchor, events, words)
                if match:
                    matched.append(match)
                else:
                    result.warnings.append(
                        f"Anchor not matched: {anchor.get('narration_anchor', '?')}"
                    )
        else:
            matched = self._auto_match(events, words)

        return matched

    def _match_configured_anchor(
        self,
        anchor_cfg: dict[str, Any],
        events: list[dict[str, Any]],
        words: list[dict[str, Any]],
    ) -> AnchorMatch | None:
        """Match a single configured anchor to an event and narration word."""
        target_action = anchor_cfg.get("action", "")
        target_selector = anchor_cfg.get("selector", "")
        narration_anchor = anchor_cfg.get("narration_anchor", "")

        event_idx = None
        for i, ev in enumerate(events):
            if target_action and ev.get("action") != target_action:
                continue
            if target_selector and ev.get("selector", "") != target_selector:
                continue
            event_idx = i
            break

        if event_idx is None:
            for i, ev in enumerate(events):
                if target_action and ev.get("action") == target_action:
                    event_idx = i
                    break

        if event_idx is None:
            return None

        narration_t = self._find_narration_time(narration_anchor, words)
        if narration_t is None:
            return None

        ev = events[event_idx]
        return AnchorMatch(
            event_idx=event_idx,
            event_t=ev["t"],
            action=ev.get("action", ""),
            selector=ev.get("selector", ""),
            narration_t=narration_t,
            narration_text=narration_anchor,
            confidence=0.9,
        )

    def _auto_match(
        self,
        events: list[dict[str, Any]],
        words: list[dict[str, Any]],
    ) -> list[AnchorMatch]:
        """Auto-detect anchors by extracting keywords from event selectors/URLs."""
        matched: list[AnchorMatch] = []
        used_words: set[int] = set()

        for i, ev in enumerate(events):
            keywords = self._extract_keywords(ev)
            if not keywords:
                continue

            best_word_idx = None
            best_word_t = None
            best_keyword = ""
            best_confidence = 0.0

            for kw in keywords:
                for wi, w in enumerate(words):
                    if wi in used_words:
                        continue
                    word_text = w.get("word", "").lower().strip(".,!?;:'\"")
                    if kw.lower() == word_text:
                        conf = 0.8
                        if best_confidence < conf:
                            best_word_idx = wi
                            best_word_t = w.get("start", 0)
                            best_keyword = kw
                            best_confidence = conf
                    elif kw.lower() in word_text or word_text in kw.lower():
                        conf = 0.5
                        if best_confidence < conf:
                            best_word_idx = wi
                            best_word_t = w.get("start", 0)
                            best_keyword = kw
                            best_confidence = conf

            if best_word_idx is not None and best_word_t is not None:
                used_words.add(best_word_idx)
                matched.append(AnchorMatch(
                    event_idx=i,
                    event_t=ev["t"],
                    action=ev.get("action", ""),
                    selector=ev.get("selector", ""),
                    narration_t=best_word_t,
                    narration_text=best_keyword,
                    confidence=best_confidence,
                ))

        return matched

    def _compute_speed_segments(
        self,
        anchors: list[AnchorMatch],
        events: list[dict[str, Any]],
        timing_entry: dict[str, Any],
    ) -> list[SpeedSegment]:
        """Build piece-wise speed segments between consecutive anchors."""
        segments: list[SpeedSegment] = []
        total_video = events[-1]["t"] if events else 0
        total_narration = self._timing_duration(timing_entry)

        points = [(0.0, 0.0)]
        for a in anchors:
            points.append((a.event_t, a.narration_t))
        points.append((total_video, total_narration))

        for i in range(len(points) - 1):
            v_start, n_start = points[i]
            v_end, n_end = points[i + 1]
            v_dur = v_end - v_start
            n_dur = n_end - n_start

            if v_dur <= 0:
                continue

            factor = n_dur / v_dur if v_dur > 0 else 1.0
            factor = max(self._min_speed, min(self._max_speed, factor))

            segments.append(SpeedSegment(
                video_start=v_start,
                video_end=v_end,
                narration_start=n_start,
                narration_end=n_end,
                factor=factor,
            ))

        return segments

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_narration_time(text: str, words: list[dict[str, Any]]) -> float | None:
        """Find the timestamp of a keyword phrase in the Whisper word list."""
        if not text or not words:
            return None

        tokens = text.lower().split()
        if not tokens:
            return None

        first_token = tokens[0]
        for w in words:
            word_text = w.get("word", "").lower().strip(".,!?;:'\"")
            if first_token == word_text or first_token in word_text:
                return float(w.get("start", 0))

        for w in words:
            word_text = w.get("word", "").lower().strip(".,!?;:'\"")
            for token in tokens:
                if token == word_text:
                    return float(w.get("start", 0))

        return None

    @staticmethod
    def _extract_keywords(event: dict[str, Any]) -> list[str]:
        """Extract searchable keywords from an event's selector, URL, or value."""
        keywords: list[str] = []

        selector = event.get("selector", "")
        if selector:
            for part in re.split(r'[#.\[\]=\s"\'><:()]+', selector):
                clean = re.sub(r"[^a-zA-Z]", "", part)
                if len(clean) >= 3:
                    keywords.append(clean)

        url = event.get("url", "")
        if url:
            path_part = url.split("//", 1)[-1] if "//" in url else url
            for part in re.split(r"[/:?&=.]+", path_part):
                clean = re.sub(r"[^a-zA-Z]", "", part)
                if len(clean) >= 3:
                    keywords.append(clean)

        value = event.get("value", "")
        if value and not value.startswith("http"):
            for word in value.split():
                clean = re.sub(r"[^a-zA-Z]", "", word)
                if len(clean) >= 3:
                    keywords.append(clean)

        return keywords

    @staticmethod
    def _timing_duration(entry: dict[str, Any]) -> float:
        max_end = 0.0
        for key in ("words", "segments"):
            for item in entry.get(key, []):
                try:
                    max_end = max(max_end, float(item.get("end", 0)))
                except (TypeError, ValueError):
                    continue
        return max_end

    def _load_timing_json(self) -> dict[str, Any]:
        path = self.config.animations_dir / "timing.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _load_events(self, seg_id: str) -> list[dict[str, Any]]:
        path = self.config.animations_dir / f"{seg_id}-events.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _write_sync_map(self, seg_id: str, result: SyncResult) -> None:
        out_dir = self.config.animations_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{seg_id}-sync_map.json"
        out_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[sync-pw] Wrote sync map to {out_path}")

    @staticmethod
    def _print_result(result: SyncResult, dry_run: bool) -> None:
        prefix = "[sync-pw] DRY-RUN" if dry_run else "[sync-pw]"
        print(
            f"{prefix} {result.segment}: {len(result.anchors)} anchor(s), "
            f"{len(result.speed_segments)} speed segment(s), "
            f"strategy={result.strategy}"
        )
        for w in result.warnings:
            print(f"{prefix}   WARN: {w}")
        for a in result.anchors[:8]:
            print(
                f"{prefix}   anchor: event@{a.event_t:.1f}s ({a.action} {a.selector[:30]}) "
                f"→ narration@{a.narration_t:.1f}s \"{a.narration_text[:30]}\" "
                f"(conf={a.confidence:.0%})"
            )
        for s in result.speed_segments[:5]:
            print(
                f"{prefix}   speed: video [{s.video_start:.1f}–{s.video_end:.1f}s] "
                f"→ narration [{s.narration_start:.1f}–{s.narration_end:.1f}s] "
                f"({s.factor:.2f}x)"
            )
