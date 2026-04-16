"""Extract browser action events from Playwright trace archives.

Playwright traces (``trace.zip``) contain a newline-delimited JSON log of
every browser action with metadata and timing.  This module parses those
traces and emits a normalized ``events.json`` suitable for narration sync.

Typical trace.zip contents::

    trace.trace          — newline-delimited JSON: context-created, action
                           entries (before/after/input), resource refs, etc.
    trace.network        — network log entries (optional)
    resources/           — screenshots, DOM snapshots, response bodies

We only care about *action* entries — ``before`` records that mark the start
of user-driven actions (click, fill, goto, …) and the paired ``after`` records
that mark completion.  From these we produce a timeline::

    [
      {"t": 0.0,  "action": "goto",  "url": "http://localhost:8501"},
      {"t": 1.23, "action": "fill",  "selector": "#email", "value": "user@example.com"},
      {"t": 3.45, "action": "click", "selector": "button[type=submit]"},
    ]
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


# Actions we care about for narration sync (user-visible interactions).
_TRACKED_ACTIONS = frozenset({
    "click",
    "dblclick",
    "fill",
    "type",
    "press",
    "check",
    "uncheck",
    "selectOption",
    "hover",
    "tap",
    "goto",
    "navigate",
    "goBack",
    "goForward",
    "reload",
    "setInputFiles",
    "dragTo",
    "selectText",
})


class TraceParseError(RuntimeError):
    """Raised when a trace file cannot be parsed."""


@dataclass
class TraceEvent:
    """A single normalised browser action event."""

    t: float
    action: str
    selector: str = ""
    url: str = ""
    value: str = ""
    page_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"t": round(self.t, 3), "action": self.action}
        if self.selector:
            d["selector"] = self.selector
        if self.url:
            d["url"] = self.url
        if self.value:
            d["value"] = self.value
        if self.page_id:
            d["page_id"] = self.page_id
        return d


@dataclass
class TraceResult:
    """Result of extracting events from one trace."""

    trace_path: str
    events: list[TraceEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    wall_start_ms: float = 0.0
    wall_end_ms: float = 0.0

    @property
    def duration_sec(self) -> float:
        if self.wall_start_ms and self.wall_end_ms:
            return (self.wall_end_ms - self.wall_start_ms) / 1000.0
        if self.events:
            return self.events[-1].t
        return 0.0


class TraceExtractor:
    """Parse Playwright trace archives and extract action events."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config

    def extract(self, trace_path: str | Path) -> TraceResult:
        """Extract events from a single trace archive or directory."""
        path = Path(trace_path)
        if path.is_dir():
            return self._extract_from_dir(path)
        if path.suffix == ".zip":
            return self._extract_from_zip(path)
        if path.suffix == ".trace" or path.name == "trace.trace":
            return self._extract_from_trace_file(path)
        raise TraceParseError(f"Unsupported trace format: {path}")

    def extract_all(self) -> list[TraceResult]:
        """Extract events from all playwright_test segments in visual_map."""
        if not self.config:
            return []

        results: list[TraceResult] = []
        for seg_id, vmap in self.config.visual_map.items():
            if vmap.get("type") != "playwright_test":
                continue
            trace_path = vmap.get("trace", "")
            if not trace_path:
                continue
            resolved = self.config.base_dir / trace_path
            if not resolved.exists():
                print(f"[trace] SKIP {seg_id}: trace not found at {resolved}")
                continue
            print(f"[trace] Extracting events from {seg_id}: {resolved}")
            result = self.extract(resolved)
            self._write_events_json(seg_id, result)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Internal parsing
    # ------------------------------------------------------------------

    def _extract_from_zip(self, zip_path: Path) -> TraceResult:
        result = TraceResult(trace_path=str(zip_path))
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                trace_names = [
                    n for n in zf.namelist()
                    if n.endswith(".trace") or n == "trace.trace"
                ]
                if not trace_names:
                    result.warnings.append("No .trace file found inside zip")
                    return result

                for trace_name in trace_names:
                    data = zf.read(trace_name).decode("utf-8", errors="replace")
                    self._parse_trace_lines(data, result)
        except zipfile.BadZipFile as exc:
            raise TraceParseError(f"Bad zip file: {zip_path}: {exc}") from exc
        return result

    def _extract_from_dir(self, dir_path: Path) -> TraceResult:
        result = TraceResult(trace_path=str(dir_path))
        trace_files = sorted(dir_path.glob("*.trace"))
        if not trace_files:
            trace_file = dir_path / "trace.trace"
            if trace_file.exists():
                trace_files = [trace_file]
        if not trace_files:
            result.warnings.append(f"No .trace files found in {dir_path}")
            return result
        for tf in trace_files:
            data = tf.read_text(encoding="utf-8", errors="replace")
            self._parse_trace_lines(data, result)
        return result

    def _extract_from_trace_file(self, trace_file: Path) -> TraceResult:
        result = TraceResult(trace_path=str(trace_file))
        data = trace_file.read_text(encoding="utf-8", errors="replace")
        self._parse_trace_lines(data, result)
        return result

    def _parse_trace_lines(self, data: str, result: TraceResult) -> None:
        """Parse newline-delimited JSON from a trace.trace file."""
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")

            if entry_type == "context-options":
                pass

            elif entry_type == "before":
                self._handle_before(entry, result)

            elif entry_type == "after":
                pass

            elif entry_type == "action":
                self._handle_action(entry, result)

            elif entry_type == "event":
                self._handle_event(entry, result)

    def _handle_before(self, entry: dict[str, Any], result: TraceResult) -> None:
        """Handle a 'before' action entry — marks the start of a user action."""
        params = entry.get("params", {})
        api_name = entry.get("apiName", "") or params.get("apiName", "")
        action_name = self._normalize_action(api_name)
        if not action_name:
            return

        wall_time = entry.get("wallTime", 0) or entry.get("startTime", 0) or 0
        if wall_time and (result.wall_start_ms == 0 or wall_time < result.wall_start_ms):
            result.wall_start_ms = wall_time

        if wall_time and wall_time > result.wall_end_ms:
            result.wall_end_ms = wall_time

        t_sec = self._compute_relative_time(wall_time, result)

        event = TraceEvent(
            t=t_sec,
            action=action_name,
            selector=params.get("selector", ""),
            url=params.get("url", ""),
            value=self._extract_value(params),
            page_id=entry.get("pageId", ""),
            raw=entry,
        )
        result.events.append(event)

    def _handle_action(self, entry: dict[str, Any], result: TraceResult) -> None:
        """Handle an 'action' entry (alternative format used by some Playwright versions)."""
        command = entry.get("command", "") or entry.get("method", "")
        action_name = self._normalize_action(command)
        if not action_name:
            return

        params = entry.get("params", {})
        wall_time = entry.get("wallTime", 0) or entry.get("startTime", 0) or 0
        if wall_time and (result.wall_start_ms == 0 or wall_time < result.wall_start_ms):
            result.wall_start_ms = wall_time
        if wall_time and wall_time > result.wall_end_ms:
            result.wall_end_ms = wall_time

        t_sec = self._compute_relative_time(wall_time, result)

        event = TraceEvent(
            t=t_sec,
            action=action_name,
            selector=params.get("selector", ""),
            url=params.get("url", ""),
            value=self._extract_value(params),
            page_id=entry.get("pageId", ""),
            raw=entry,
        )
        result.events.append(event)

    def _handle_event(self, entry: dict[str, Any], result: TraceResult) -> None:
        """Handle an 'event' entry (e.g. navigation events)."""
        method = entry.get("method", "")
        if method not in ("navigated", "navigatedWithinDocument"):
            return
        params = entry.get("params", {})
        wall_time = entry.get("wallTime", 0) or entry.get("time", 0) or 0
        if wall_time and (result.wall_start_ms == 0 or wall_time < result.wall_start_ms):
            result.wall_start_ms = wall_time
        if wall_time and wall_time > result.wall_end_ms:
            result.wall_end_ms = wall_time

        t_sec = self._compute_relative_time(wall_time, result)
        event = TraceEvent(
            t=t_sec,
            action="navigate",
            url=params.get("url", ""),
            page_id=entry.get("pageId", ""),
            raw=entry,
        )
        result.events.append(event)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_action(api_name: str) -> str:
        """Map Playwright API names to canonical action names.

        Examples:
          'page.click'       → 'click'
          'locator.fill'     → 'fill'
          'page.goto'        → 'goto'
          'frame.check'      → 'check'
          'elementHandle.click' → 'click'
        """
        if not api_name:
            return ""
        parts = api_name.rsplit(".", 1)
        method = parts[-1] if len(parts) > 1 else parts[0]
        method_lower = method.lower()

        canonical_map = {
            "click": "click",
            "dblclick": "dblclick",
            "fill": "fill",
            "type": "type",
            "press": "press",
            "check": "check",
            "uncheck": "uncheck",
            "selectoption": "selectOption",
            "hover": "hover",
            "tap": "tap",
            "goto": "goto",
            "navigate": "navigate",
            "goback": "goBack",
            "goforward": "goForward",
            "reload": "reload",
            "setinputfiles": "setInputFiles",
            "dragto": "dragTo",
            "selecttext": "selectText",
        }
        return canonical_map.get(method_lower, "")

    @staticmethod
    def _compute_relative_time(wall_time_ms: float, result: TraceResult) -> float:
        """Convert absolute wall-clock time to seconds relative to trace start."""
        if not wall_time_ms or not result.wall_start_ms:
            return 0.0
        return max(0.0, (wall_time_ms - result.wall_start_ms) / 1000.0)

    @staticmethod
    def _extract_value(params: dict[str, Any]) -> str:
        """Pull the most useful 'value' from action params."""
        for key in ("value", "text", "url", "key", "files"):
            v = params.get(key)
            if v is not None:
                if isinstance(v, list):
                    return ", ".join(str(x) for x in v[:3])
                return str(v)[:200]
        return ""

    def _write_events_json(self, seg_id: str, result: TraceResult) -> None:
        """Write extracted events to the animations directory."""
        if not self.config:
            return
        out_dir = self.config.animations_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{seg_id}-events.json"
        events_data = [e.to_dict() for e in result.events]
        out_path.write_text(
            json.dumps(events_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[trace] Wrote {len(result.events)} events to {out_path}")


# ---------------------------------------------------------------------------
# Convenience: load events from JSON
# ---------------------------------------------------------------------------


def load_events_json(path: str | Path) -> list[dict[str, Any]]:
    """Load a previously-written events.json file."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []
