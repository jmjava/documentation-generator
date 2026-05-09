"""Parse Playwright ``trace.zip`` files into ordered action timelines.

Playwright records a trace alongside the video when invoked with
``--trace=on``. The trace is a ZIP archive containing a JSONL file
``trace.trace`` (one JSON event per line). Each user-callable API invocation
emits a pair of events keyed by ``callId``:

  ``{"type": "before", "callId": "...", "startTime": <ms>, "apiName": "page.goto", ...}``
  ``{"type": "after",  "callId": "...", "endTime":   <ms>, ...}``

We extract only the user-facing surface (``page.*``, ``locator.*``,
``expect.*``, ``frame.*``, ``keyboard.*``, ``mouse.*``) and return them in
start-time order so downstream code can align them with manifest
``narration_steps`` and place TTS clips at real recording-time offsets.

The parser is tolerant of format drift across Playwright versions: missing or
unknown fields produce a best-effort entry rather than an exception. Empty or
malformed traces yield an empty list — callers fall back to single-clip
narration in that case.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

# API prefixes considered "user-visible" — these are the calls a spec author
# typed (or that ``expect`` synthesised). Internal Playwright machinery
# (``tracing.*``, ``browserContext._*``, ``page._*``) is filtered out so the
# timeline aligns one-to-one with the actions a viewer sees on screen.
_USER_API_PREFIXES: tuple[str, ...] = (
    "page.",
    "locator.",
    "expect.",
    "frame.",
    "frameLocator.",
    "keyboard.",
    "mouse.",
    "elementHandle.",
)

# Calls that exist in the user surface but are never visually meaningful — we
# drop them so they don't consume narration slots.
_DROP_API_NAMES: frozenset[str] = frozenset(
    {
        "page.context",
        "page.mainFrame",
        "page.url",
        "page.viewportSize",
        "page.video",
        "page.evaluateHandle",
        "frame.page",
        "frame.url",
        "frame.name",
        "frame.parentFrame",
    }
)


@dataclass(frozen=True)
class TraceAction:
    """One user-visible Playwright API invocation, timed to the recording."""

    call_id: str
    api_name: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def find_trace_zip(search_root: Path) -> Path | None:
    """Locate the most recent ``trace.zip`` under ``search_root``.

    Playwright writes traces to a per-test subdirectory of the configured
    ``output-dir``. We pick the largest file (the main trace, as opposed to
    retry copies) to be robust against retries.
    """
    if not search_root.exists():
        return None
    candidates = list(search_root.rglob("trace.zip"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def parse_trace_zip(trace_zip: Path) -> list[TraceAction]:
    """Return the ordered list of user-visible API actions in ``trace_zip``.

    Implementation notes:

    * Reads every ``*.trace`` file in the archive (Playwright ships
      ``test.trace`` plus one or more ``N-trace.trace`` shards; both
      contain events on the same internal clock).
    * Pairs ``before`` / ``after`` events by ``callId`` and filters down
      to user-visible APIs (see :data:`_USER_API_PREFIXES`).
    * **Anchors timestamps to the WebM clock, not the trace clock.** The
      trace's ``screencast-frame`` events carry a ``timestamp`` field on
      the SAME internal Playwright clock as ``before.startTime``. The
      smallest such timestamp is the moment the video file begins —
      anything earlier in the trace fired before recording started and
      simply isn't on screen. Using the first screencast as the origin
      means action timestamps line up with frames in the captured WebM
      (otherwise context setup / first navigation can land BEFORE
      ``video_t=0`` and we'd display the wrong frame for early
      narration lines). When no ``screencast-frame`` is present
      (defensive — empty trace, headed mode without video, etc.) we
      fall back to ``min(startTime)``.
    * Returned actions are sorted by ``start_ms`` (recording-relative).
    """
    if not trace_zip.is_file():
        return []
    starts: dict[str, tuple[str, int]] = {}
    ends: dict[str, int] = {}
    screencast_timestamps: list[int] = []
    with zipfile.ZipFile(trace_zip) as zf:
        trace_names = [
            n for n in zf.namelist() if n.endswith(".trace")
        ]
        for name in trace_names:
            try:
                raw = zf.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(evt, dict):
                    continue
                etype = evt.get("type")
                if etype == "screencast-frame":
                    ts = _coerce_ms(evt.get("timestamp"))
                    if ts is not None:
                        screencast_timestamps.append(ts)
                    continue
                call_id = evt.get("callId")
                if not isinstance(call_id, str):
                    continue
                if etype == "before":
                    api = _coerce_api_name(evt)
                    if api is None:
                        continue
                    start_raw = (
                        evt.get("startTime")
                        if "startTime" in evt
                        else evt.get("wallTime")
                    )
                    start_ms = _coerce_ms(start_raw)
                    if start_ms is None:
                        continue
                    starts[call_id] = (api, start_ms)
                elif etype == "after":
                    end_raw = evt.get("endTime")
                    end_ms = _coerce_ms(end_raw)
                    if end_ms is None:
                        continue
                    ends[call_id] = end_ms

    if not starts:
        return []

    base = _resolve_video_origin(screencast_timestamps, starts)

    actions: list[TraceAction] = []
    for call_id, (api, start_ms) in starts.items():
        if not _is_user_visible(api):
            continue
        end_ms = ends.get(call_id, start_ms)
        actions.append(
            TraceAction(
                call_id=call_id,
                api_name=api,
                start_ms=max(0, start_ms - base),
                end_ms=max(0, end_ms - base),
            )
        )
    actions.sort(key=lambda a: a.start_ms)
    return actions


def _resolve_video_origin(
    screencast_timestamps: list[int],
    starts: dict[str, tuple[str, int]],
) -> int:
    """Pick the time-zero anchor for video-relative action timestamps.

    Preference is the smallest ``screencast-frame.timestamp`` (= moment
    the WebM begins recording). When the trace contains no screencast
    frames we fall back to ``min(before.startTime)`` so callers still
    get monotonically non-negative offsets, even if the resulting
    timeline is recording-clock instead of video-clock.
    """
    if screencast_timestamps:
        return min(screencast_timestamps)
    return min(start for _api, start in starts.values())


def _coerce_api_name(evt: dict) -> str | None:
    """Pull a stable lowercase ``class.method`` name from a ``before`` event."""
    api = evt.get("apiName")
    if isinstance(api, str) and api:
        return api.strip()
    cls = evt.get("class")
    method = evt.get("method")
    if isinstance(cls, str) and isinstance(method, str) and cls and method:
        # ``Page`` / ``Locator`` -> ``page`` / ``locator`` (Playwright's
        # internal naming convention for trace events).
        return f"{cls[0].lower()}{cls[1:]}.{method}"
    return None


def _coerce_ms(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _is_user_visible(api_name: str) -> bool:
    if api_name in _DROP_API_NAMES:
        return False
    return any(api_name.startswith(prefix) for prefix in _USER_API_PREFIXES)


def build_timeline(
    actions: list[TraceAction],
    narration_steps: list[dict],
) -> list[dict]:
    """Zip ``narration_steps`` onto trace ``actions`` in order.

    Returns a list of ``{"say": ..., "t_start_ms": ...}`` entries consumable by
    :func:`docgen.demo_function._align_visual_to_narration` (the audio-driven
    Whisper-aligned narration path). When the lengths differ we align by
    index up to ``min(len(steps), len(actions))`` — extra entries on either
    side are dropped, and a warning is the caller's job to surface (we keep
    this function pure / side-effect-free).

    Each ``narration_steps`` entry must be a mapping with at least a string
    ``say`` field; the optional ``api_name`` is used as a soft sanity check
    (mismatches do not raise — they are reported via the return shape's
    ``alignment_mismatch`` flag in the future if we add one).
    """
    timeline: list[dict] = []
    n = min(len(actions), len(narration_steps))
    for i in range(n):
        step = narration_steps[i]
        if not isinstance(step, dict):
            continue
        say = step.get("say")
        if not isinstance(say, str) or not say.strip():
            continue
        timeline.append(
            {
                "say": say.strip(),
                "t_start_ms": int(actions[i].start_ms),
                "api_name": actions[i].api_name,
            }
        )
    return timeline
