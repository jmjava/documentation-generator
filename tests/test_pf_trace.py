"""Tests for ``docgen.pf_trace`` — Playwright trace.zip parsing."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from docgen.pf_trace import (
    TraceAction,
    build_timeline,
    find_trace_zip,
    parse_trace_zip,
)


def _write_trace_zip(
    path: Path, events: list[dict], *, filename: str = "trace.trace"
) -> Path:
    """Write a synthetic Playwright ``trace.zip`` containing ``events`` as JSONL."""
    body = "\n".join(json.dumps(e) for e in events) + "\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(filename, body)
    return path


def test_parse_trace_zip_pairs_before_after_and_normalises_timestamps(
    tmp_path: Path,
) -> None:
    trace_zip = tmp_path / "trace.zip"
    _write_trace_zip(
        trace_zip,
        [
            {
                "type": "before",
                "callId": "c1",
                "apiName": "page.goto",
                "startTime": 1_000,
            },
            {"type": "after", "callId": "c1", "endTime": 1_300},
            {
                "type": "before",
                "callId": "c2",
                "apiName": "locator.click",
                "startTime": 1_500,
            },
            {"type": "after", "callId": "c2", "endTime": 1_700},
        ],
    )
    actions = parse_trace_zip(trace_zip)
    assert [a.api_name for a in actions] == ["page.goto", "locator.click"]
    assert actions[0].start_ms == 0
    assert actions[1].start_ms == 500
    assert actions[0].duration_ms == 300
    assert actions[1].duration_ms == 200


def test_parse_trace_zip_filters_internal_apis(tmp_path: Path) -> None:
    trace_zip = tmp_path / "trace.zip"
    _write_trace_zip(
        trace_zip,
        [
            {
                "type": "before",
                "callId": "c1",
                "apiName": "browser.newContext",
                "startTime": 100,
            },
            {"type": "after", "callId": "c1", "endTime": 110},
            {
                "type": "before",
                "callId": "c2",
                "apiName": "tracing.start",
                "startTime": 200,
            },
            {"type": "after", "callId": "c2", "endTime": 210},
            {
                "type": "before",
                "callId": "c3",
                "apiName": "page.goto",
                "startTime": 300,
            },
            {"type": "after", "callId": "c3", "endTime": 400},
        ],
    )
    actions = parse_trace_zip(trace_zip)
    assert [a.api_name for a in actions] == ["page.goto"]


def test_parse_trace_zip_handles_class_method_fallback(tmp_path: Path) -> None:
    """Older Playwright traces split apiName into ``class`` + ``method``."""
    trace_zip = tmp_path / "trace.zip"
    _write_trace_zip(
        trace_zip,
        [
            {
                "type": "before",
                "callId": "c1",
                "class": "Page",
                "method": "click",
                "startTime": 50,
            },
            {"type": "after", "callId": "c1", "endTime": 75},
        ],
    )
    actions = parse_trace_zip(trace_zip)
    assert [a.api_name for a in actions] == ["page.click"]


def test_parse_trace_zip_drops_unpaired_events(tmp_path: Path) -> None:
    trace_zip = tmp_path / "trace.zip"
    _write_trace_zip(
        trace_zip,
        [
            {
                "type": "before",
                "callId": "c1",
                "apiName": "page.goto",
                "startTime": 100,
            },
            {
                "type": "before",
                "callId": "c2",
                "apiName": "locator.click",
                "startTime": 200,
            },
            {"type": "after", "callId": "c2", "endTime": 250},
        ],
    )
    actions = parse_trace_zip(trace_zip)
    api_names = [a.api_name for a in actions]
    assert "locator.click" in api_names
    goto = next(a for a in actions if a.api_name == "page.goto")
    assert goto.duration_ms == 0


def test_parse_trace_zip_returns_empty_on_garbage(tmp_path: Path) -> None:
    trace_zip = tmp_path / "trace.zip"
    with zipfile.ZipFile(trace_zip, "w") as zf:
        zf.writestr("trace.trace", "not json\n{maybe?}\n")
    assert parse_trace_zip(trace_zip) == []


def test_parse_trace_zip_returns_empty_when_missing(tmp_path: Path) -> None:
    assert parse_trace_zip(tmp_path / "nope.zip") == []


def test_find_trace_zip_picks_largest(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    small = tmp_path / "a" / "trace.zip"
    big = tmp_path / "b" / "trace.zip"
    _write_trace_zip(small, [{"type": "before", "callId": "x", "startTime": 1}])
    _write_trace_zip(
        big,
        [
            {
                "type": "before",
                "callId": "x",
                "apiName": "page.goto",
                "startTime": 1,
            },
            {"type": "after", "callId": "x", "endTime": 2},
        ]
        * 50,
    )
    found = find_trace_zip(tmp_path)
    assert found is not None
    assert found.stat().st_size >= small.stat().st_size


def test_find_trace_zip_returns_none_when_absent(tmp_path: Path) -> None:
    assert find_trace_zip(tmp_path) is None


def test_build_timeline_zips_steps_to_actions_in_order() -> None:
    actions = [
        TraceAction(call_id="c1", api_name="page.goto", start_ms=0, end_ms=200),
        TraceAction(
            call_id="c2", api_name="locator.click", start_ms=400, end_ms=500
        ),
    ]
    steps = [
        {"api_name": "page.goto", "say": "navigate to home"},
        {"api_name": "locator.click", "say": "click the start button"},
    ]
    timeline = build_timeline(actions, steps)
    assert timeline == [
        {"say": "navigate to home", "t_start_ms": 0, "api_name": "page.goto"},
        {
            "say": "click the start button",
            "t_start_ms": 400,
            "api_name": "locator.click",
        },
    ]


def test_build_timeline_truncates_to_shorter_input() -> None:
    actions = [
        TraceAction(call_id="c1", api_name="page.goto", start_ms=0, end_ms=200),
        TraceAction(call_id="c2", api_name="locator.click", start_ms=400, end_ms=500),
        TraceAction(call_id="c3", api_name="locator.fill", start_ms=600, end_ms=700),
    ]
    steps = [
        {"api_name": "page.goto", "say": "first"},
        {"api_name": "locator.click", "say": "second"},
    ]
    timeline = build_timeline(actions, steps)
    assert len(timeline) == 2
    assert [t["say"] for t in timeline] == ["first", "second"]


def test_build_timeline_skips_steps_without_say() -> None:
    actions = [
        TraceAction(call_id="c1", api_name="page.goto", start_ms=0, end_ms=200),
    ]
    steps = [{"api_name": "page.goto", "say": ""}]
    assert build_timeline(actions, steps) == []


def test_parse_trace_zip_uses_first_screencast_frame_as_origin(
    tmp_path: Path,
) -> None:
    """Action timestamps must be measured against the WebM clock.

    Playwright begins recording video LATER than it begins tracing — there
    is always some context-create + first-navigation overhead before the
    first ``screencast-frame`` is captured. The timeline our renderer
    consumes must therefore be anchored to the first screencast frame
    (which is the moment WebM ``t=0`` lives at), not to the trace's
    earliest ``before`` event. Otherwise actions that fired pre-recording
    map onto wrong frames in the output video.
    """
    trace_zip = tmp_path / "trace.zip"
    _write_trace_zip(
        trace_zip,
        [
            # context setup happens earlier than the first screencast
            {
                "type": "before",
                "callId": "ctx",
                "class": "BrowserContext",
                "method": "newPage",
                "startTime": 1000,
            },
            {"type": "after", "callId": "ctx", "endTime": 1020},
            # goto fires BEFORE the recording begins
            {
                "type": "before",
                "callId": "g1",
                "apiName": "frame.goto",
                "startTime": 1050,
            },
            {"type": "after", "callId": "g1", "endTime": 1080},
            # the WebM begins recording HERE
            {"type": "screencast-frame", "timestamp": 1200},
            # later events
            {
                "type": "before",
                "callId": "c1",
                "apiName": "locator.click",
                "startTime": 1400,
            },
            {"type": "after", "callId": "c1", "endTime": 1450},
            {"type": "screencast-frame", "timestamp": 1216},
            {"type": "screencast-frame", "timestamp": 1232},
        ],
    )
    actions = parse_trace_zip(trace_zip)
    by_api = {a.api_name: a for a in actions}
    # frame.goto fired at trace 1050 but recording starts at 1200, so its
    # video-relative timestamp clamps to 0 — it happened off-camera.
    assert by_api["frame.goto"].start_ms == 0
    assert by_api["frame.goto"].end_ms == 0
    # locator.click fired at trace 1400 → video t = 200ms.
    assert by_api["locator.click"].start_ms == 200
    assert by_api["locator.click"].end_ms == 250


def test_parse_trace_zip_falls_back_to_starts_when_no_screencast(
    tmp_path: Path,
) -> None:
    """Headless / no-video runs leave no screencast frames in the trace.

    The legacy "min(startTime)" anchor is still the right choice in that
    case — there's no WebM to align against, so the recording-clock
    timeline is the most useful thing we can return.
    """
    trace_zip = tmp_path / "trace.zip"
    _write_trace_zip(
        trace_zip,
        [
            {
                "type": "before",
                "callId": "g",
                "apiName": "frame.goto",
                "startTime": 5000,
            },
            {"type": "after", "callId": "g", "endTime": 5100},
            {
                "type": "before",
                "callId": "c",
                "apiName": "locator.click",
                "startTime": 5300,
            },
            {"type": "after", "callId": "c", "endTime": 5320},
        ],
    )
    actions = parse_trace_zip(trace_zip)
    by_api = {a.api_name: a for a in actions}
    assert by_api["frame.goto"].start_ms == 0
    assert by_api["locator.click"].start_ms == 300


def test_parse_trace_zip_finds_screencast_across_shards(tmp_path: Path) -> None:
    """``test.trace`` and ``N-trace.trace`` shards must both be scanned."""
    trace_zip = tmp_path / "trace.zip"
    body_test = json.dumps(
        {
            "type": "before",
            "callId": "g",
            "apiName": "frame.goto",
            "startTime": 1050,
        }
    ) + "\n" + json.dumps({"type": "after", "callId": "g", "endTime": 1080}) + "\n"
    body_main = (
        json.dumps({"type": "screencast-frame", "timestamp": 1200})
        + "\n"
        + json.dumps(
            {
                "type": "before",
                "callId": "c",
                "apiName": "locator.click",
                "startTime": 1400,
            }
        )
        + "\n"
        + json.dumps({"type": "after", "callId": "c", "endTime": 1450})
        + "\n"
    )
    with zipfile.ZipFile(trace_zip, "w") as zf:
        zf.writestr("test.trace", body_test)
        zf.writestr("0-trace.trace", body_main)
    actions = parse_trace_zip(trace_zip)
    by_api = {a.api_name: a for a in actions}
    assert by_api["frame.goto"].start_ms == 0  # off-camera
    assert by_api["locator.click"].start_ms == 200
