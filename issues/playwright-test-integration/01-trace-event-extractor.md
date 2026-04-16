# Issue: Playwright Trace Event Extractor

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** High (foundational)
**Depends on:** None

## Summary

Create `playwright_trace.py` — a module that parses Playwright trace files (`trace.zip`) to extract a timeline of browser actions with precise timestamps. This is the foundational data source for synchronizing narration audio with Playwright test video.

## Background

Playwright traces contain a structured JSON log of every user action (clicks, fills, navigations) with precise wall-clock timestamps. By extracting these events, we can map "what happened in the video" to "what the narration says" — the same way `tape_sync.py` maps VHS Sleep blocks to timing.json, and Manim scenes use `wait_until` to sync with Whisper segments.

## Acceptance Criteria

- [ ] Parse Playwright `trace.zip` files and extract action events
- [ ] Support action types: `click`, `fill`, `type`, `press`, `goto`/`navigate`, `select_option`, `check`, `uncheck`, `hover`, `dblclick`, `drag_to`
- [ ] Each event includes: timestamp (relative to video start), action type, selector, optional value (typed text, URL)
- [ ] Output `events.json` with normalized timestamps:
  ```json
  [
    {"t": 0.0, "action": "goto", "url": "http://localhost:8501"},
    {"t": 1.2, "action": "fill", "selector": "#email", "value": "user@example.com"},
    {"t": 3.4, "action": "click", "selector": "button[type=submit]"},
    {"t": 5.1, "action": "goto", "url": "/dashboard"}
  ]
  ```
- [ ] Handle multi-page traces and iframes
- [ ] CLI command: `docgen trace-extract [--test test_name] [--output events.json]`
- [ ] Unit tests with fixture trace zip files

## Technical Notes

Playwright traces are zip archives containing:
- `trace.trace` — binary trace events (protobuf-like)
- `trace.network` — network events
- Resources (screenshots, etc.)

The trace format has been stable since Playwright 1.12+. We should parse the action entries from the trace resources JSON, filtering for user-initiated actions vs internal Playwright bookkeeping.

The `events.json` format should be extensible for future action types and metadata (screenshots at event time, DOM snapshots, etc.).

## Files to Create/Modify

- **Create:** `src/docgen/playwright_trace.py`
- **Modify:** `src/docgen/cli.py` (add `trace-extract` command)
- **Create:** `tests/test_playwright_trace.py`
- **Create:** `tests/fixtures/` (sample trace.zip files)
