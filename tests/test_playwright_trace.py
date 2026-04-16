"""Tests for docgen.playwright_trace — Playwright trace event extraction."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from docgen.playwright_trace import (
    TraceEvent,
    TraceExtractor,
    TraceParseError,
    TraceResult,
    load_events_json,
)


# ---------------------------------------------------------------------------
# Helpers: build fake trace data
# ---------------------------------------------------------------------------


def _make_trace_lines(events: list[dict]) -> str:
    """Build newline-delimited JSON like Playwright's trace.trace format."""
    return "\n".join(json.dumps(e) for e in events)


def _make_trace_zip(tmp_path: Path, trace_content: str, name: str = "test-trace.zip") -> Path:
    """Create a trace.zip with a trace.trace file inside."""
    zip_path = tmp_path / name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("trace.trace", trace_content)
    zip_path.write_bytes(buf.getvalue())
    return zip_path


SAMPLE_EVENTS = [
    {
        "type": "context-options",
        "browserName": "chromium",
    },
    {
        "type": "before",
        "apiName": "page.goto",
        "wallTime": 1000000,
        "params": {"url": "http://localhost:8501"},
        "pageId": "page-1",
    },
    {
        "type": "after",
        "apiName": "page.goto",
        "wallTime": 1001200,
    },
    {
        "type": "before",
        "apiName": "locator.fill",
        "wallTime": 1001200,
        "params": {"selector": "#email", "value": "user@example.com"},
        "pageId": "page-1",
    },
    {
        "type": "after",
        "apiName": "locator.fill",
        "wallTime": 1001500,
    },
    {
        "type": "before",
        "apiName": "locator.click",
        "wallTime": 1003400,
        "params": {"selector": "button[type=submit]"},
        "pageId": "page-1",
    },
    {
        "type": "after",
        "apiName": "locator.click",
        "wallTime": 1003600,
    },
]


# ---------------------------------------------------------------------------
# TraceEvent
# ---------------------------------------------------------------------------


class TestTraceEvent:
    def test_to_dict_minimal(self):
        e = TraceEvent(t=1.5, action="click")
        d = e.to_dict()
        assert d == {"t": 1.5, "action": "click"}

    def test_to_dict_full(self):
        e = TraceEvent(
            t=2.345,
            action="fill",
            selector="#email",
            value="user@example.com",
            url="",
            page_id="page-1",
        )
        d = e.to_dict()
        assert d["t"] == 2.345
        assert d["action"] == "fill"
        assert d["selector"] == "#email"
        assert d["value"] == "user@example.com"
        assert "url" not in d  # empty strings omitted
        assert d["page_id"] == "page-1"


# ---------------------------------------------------------------------------
# TraceResult
# ---------------------------------------------------------------------------


class TestTraceResult:
    def test_duration_from_wall_times(self):
        r = TraceResult(
            trace_path="test.zip",
            wall_start_ms=1000000,
            wall_end_ms=1005000,
        )
        assert r.duration_sec == pytest.approx(5.0)

    def test_duration_from_events(self):
        r = TraceResult(
            trace_path="test.zip",
            events=[
                TraceEvent(t=0.0, action="goto"),
                TraceEvent(t=3.5, action="click"),
            ],
        )
        assert r.duration_sec == pytest.approx(3.5)

    def test_duration_empty(self):
        r = TraceResult(trace_path="test.zip")
        assert r.duration_sec == 0.0


# ---------------------------------------------------------------------------
# TraceExtractor — from zip
# ---------------------------------------------------------------------------


class TestTraceExtractorZip:
    def test_extract_basic_events(self, tmp_path):
        trace_content = _make_trace_lines(SAMPLE_EVENTS)
        zip_path = _make_trace_zip(tmp_path, trace_content)

        extractor = TraceExtractor()
        result = extractor.extract(zip_path)

        assert len(result.events) == 3
        assert result.events[0].action == "goto"
        assert result.events[0].url == "http://localhost:8501"
        assert result.events[1].action == "fill"
        assert result.events[1].selector == "#email"
        assert result.events[1].value == "user@example.com"
        assert result.events[2].action == "click"
        assert result.events[2].selector == "button[type=submit]"

    def test_relative_timestamps(self, tmp_path):
        trace_content = _make_trace_lines(SAMPLE_EVENTS)
        zip_path = _make_trace_zip(tmp_path, trace_content)

        result = TraceExtractor().extract(zip_path)

        assert result.events[0].t == pytest.approx(0.0)
        assert result.events[1].t == pytest.approx(1.2)
        assert result.events[2].t == pytest.approx(3.4)

    def test_ignores_non_tracked_actions(self, tmp_path):
        events = [
            {
                "type": "before",
                "apiName": "page.waitForSelector",
                "wallTime": 1000000,
                "params": {"selector": ".loaded"},
            },
            {
                "type": "before",
                "apiName": "page.goto",
                "wallTime": 1001000,
                "params": {"url": "http://localhost"},
            },
        ]
        trace_content = _make_trace_lines(events)
        zip_path = _make_trace_zip(tmp_path, trace_content)

        result = TraceExtractor().extract(zip_path)
        assert len(result.events) == 1
        assert result.events[0].action == "goto"

    def test_empty_zip_warns(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.md", "no trace here")
        zip_path = tmp_path / "empty.zip"
        zip_path.write_bytes(buf.getvalue())

        result = TraceExtractor().extract(zip_path)
        assert len(result.events) == 0
        assert any("No .trace file" in w for w in result.warnings)

    def test_bad_zip_raises(self, tmp_path):
        bad_path = tmp_path / "bad.zip"
        bad_path.write_bytes(b"not a zip file")

        with pytest.raises(TraceParseError, match="Bad zip"):
            TraceExtractor().extract(bad_path)


# ---------------------------------------------------------------------------
# TraceExtractor — from trace file
# ---------------------------------------------------------------------------


class TestTraceExtractorFile:
    def test_extract_from_trace_file(self, tmp_path):
        trace_content = _make_trace_lines(SAMPLE_EVENTS)
        trace_file = tmp_path / "trace.trace"
        trace_file.write_text(trace_content, encoding="utf-8")

        result = TraceExtractor().extract(trace_file)
        assert len(result.events) == 3

    def test_extract_from_dir(self, tmp_path):
        trace_content = _make_trace_lines(SAMPLE_EVENTS)
        trace_dir = tmp_path / "traces"
        trace_dir.mkdir()
        (trace_dir / "test.trace").write_text(trace_content, encoding="utf-8")

        result = TraceExtractor().extract(trace_dir)
        assert len(result.events) == 3


# ---------------------------------------------------------------------------
# TraceExtractor — normalize_action
# ---------------------------------------------------------------------------


class TestNormalizeAction:
    @pytest.mark.parametrize(
        "api_name,expected",
        [
            ("page.click", "click"),
            ("locator.click", "click"),
            ("page.goto", "goto"),
            ("locator.fill", "fill"),
            ("page.dblclick", "dblclick"),
            ("locator.check", "check"),
            ("locator.selectOption", "selectOption"),
            ("elementHandle.hover", "hover"),
            ("page.reload", "reload"),
            ("locator.dragTo", "dragTo"),
            ("page.waitForSelector", ""),
            ("page.evaluate", ""),
            ("page.screenshot", ""),
            ("", ""),
        ],
    )
    def test_action_normalization(self, api_name, expected):
        assert TraceExtractor._normalize_action(api_name) == expected


# ---------------------------------------------------------------------------
# TraceExtractor — action entry format
# ---------------------------------------------------------------------------


class TestActionEntryFormat:
    def test_action_type_entries(self, tmp_path):
        """Some Playwright versions use type='action' instead of type='before'."""
        events = [
            {
                "type": "action",
                "command": "page.goto",
                "wallTime": 1000000,
                "params": {"url": "http://localhost"},
            },
            {
                "type": "action",
                "command": "locator.click",
                "wallTime": 1002000,
                "params": {"selector": "#btn"},
            },
        ]
        trace_content = _make_trace_lines(events)
        zip_path = _make_trace_zip(tmp_path, trace_content)

        result = TraceExtractor().extract(zip_path)
        assert len(result.events) == 2
        assert result.events[0].action == "goto"
        assert result.events[1].action == "click"

    def test_navigation_events(self, tmp_path):
        events = [
            {
                "type": "event",
                "method": "navigated",
                "wallTime": 1000000,
                "params": {"url": "http://localhost/dashboard"},
                "pageId": "page-1",
            },
        ]
        trace_content = _make_trace_lines(events)
        zip_path = _make_trace_zip(tmp_path, trace_content)

        result = TraceExtractor().extract(zip_path)
        assert len(result.events) == 1
        assert result.events[0].action == "navigate"
        assert result.events[0].url == "http://localhost/dashboard"


# ---------------------------------------------------------------------------
# load_events_json
# ---------------------------------------------------------------------------


class TestLoadEventsJson:
    def test_load_valid(self, tmp_path):
        data = [{"t": 0.0, "action": "goto"}, {"t": 1.5, "action": "click"}]
        p = tmp_path / "events.json"
        p.write_text(json.dumps(data), encoding="utf-8")

        loaded = load_events_json(p)
        assert len(loaded) == 2
        assert loaded[0]["action"] == "goto"

    def test_load_missing_file(self, tmp_path):
        loaded = load_events_json(tmp_path / "nope.json")
        assert loaded == []

    def test_load_bad_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        loaded = load_events_json(p)
        assert loaded == []

    def test_load_non_list(self, tmp_path):
        p = tmp_path / "obj.json"
        p.write_text('{"key": "val"}', encoding="utf-8")
        loaded = load_events_json(p)
        assert loaded == []
