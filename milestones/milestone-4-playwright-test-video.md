# Milestone 4 — Playwright Test Video Integration

**Goal:** Allow docgen to piggyback on existing Playwright test suites, using their recorded videos as visual sources instead of (or alongside) Manim animations. Synchronize narration audio to Playwright browser events (clicks, navigations, typed input) the same way Manim scenes sync to `timing.json`.

## Motivation

Many projects already have Playwright end-to-end tests that exercise the exact UI flows a demo video would show. Today, docgen requires either:
- **Manim** — programmatic animations (high effort, no real UI)
- **VHS** — terminal recordings (CLI-only)
- **Custom Playwright scripts** — purpose-built capture scripts separate from tests

This milestone eliminates the duplicate effort by letting teams **reuse existing Playwright tests as-is**, harvesting the video recordings Playwright already produces, and synchronizing narration to the click/navigation events that naturally occur during test execution.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Existing Playwright Tests                     │
│  (test_login.py, test_dashboard.py, etc.)                       │
│                                                                 │
│  Playwright config: video: { dir: 'test-results/videos' }      │
│  ─────────────────────────────────────────────────────────────  │
│  test_login:                                                    │
│    page.goto("/login")                                          │
│    page.fill("#email", "user@example.com")  ← event @ 1.2s     │
│    page.click("button[type=submit]")        ← event @ 3.4s     │
│    expect(page).to_have_url("/dashboard")   ← event @ 5.1s     │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  docgen Playwright Harvester                     │
│                                                                 │
│  1. Run tests with tracing + video enabled                      │
│  2. Extract event timeline from trace.zip                       │
│  3. Produce events.json:                                        │
│     [                                                           │
│       {"t": 1.2, "action": "fill", "selector": "#email"},      │
│       {"t": 3.4, "action": "click", "selector": "button"},     │
│       {"t": 5.1, "action": "navigate", "url": "/dashboard"}    │
│     ]                                                           │
│  4. Map events.json → narration segment boundaries              │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   docgen Playwright Sync                         │
│  (analogous to tape_sync.py for VHS, scenes.py for Manim)       │
│                                                                 │
│  Inputs:                                                        │
│    - events.json (from trace extraction)                        │
│    - timing.json (from Whisper timestamps)                      │
│  Output:                                                        │
│    - sync_map.json: maps narration words/segments to video      │
│      timestamps where matching UI events occur                  │
│    - Speed-adjusted video (ffmpeg setpts) or segment cut-points │
│      so narration aligns with visual actions                    │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   docgen compose (existing)                      │
│                                                                 │
│  Muxes speed-adjusted Playwright video + narration audio        │
│  using the same ffmpeg pipeline as other visual types            │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Trace-Based Event Extraction (not code instrumentation)

Rather than requiring users to modify their tests, we parse Playwright's **trace files** (`trace.zip`). Playwright traces contain a structured JSON log of every action with precise timestamps. This is non-invasive — tests run exactly as they would normally.

### 2. Event-to-Narration Alignment Strategy

Analogous to how `tape_sync.py` distributes narration duration across VHS Type/Enter/Sleep blocks, the Playwright sync will:
- Parse the event timeline from trace data
- Match events to narration segments (by configured mapping or auto-detection)
- Compute speed adjustment factors per segment so that key UI moments align with the corresponding narration words
- Apply `ffmpeg setpts` filters to speed up idle periods and slow down action-heavy periods

### 3. New Visual Map Type: `playwright_test`

Distinct from the existing `type: playwright` (custom capture scripts), the new `type: playwright_test` works with pre-existing test suites:

```yaml
visual_map:
  "03":
    type: playwright_test
    test: tests/e2e/test_wizard.py::test_setup_flow
    source: test-results/videos/test_wizard/test_setup_flow.webm
    trace: test-results/traces/test_wizard/test_setup_flow/trace.zip
    events:
      - narration_anchor: "fill in the email"
        action: fill
        selector: "#email"
      - narration_anchor: "click submit"
        action: click
        selector: "button[type=submit]"
```

### 4. Fallback Behavior

If no trace is available, the system falls back to simple duration-based sync (like the existing Playwright type), just using the test video as a flat visual source.

## Items

### Issue 1: Playwright Trace Event Extractor (`playwright_trace.py`)
- [ ] Parse Playwright `trace.zip` files to extract action events with timestamps
- [ ] Support action types: `click`, `fill`, `type`, `press`, `goto`/`navigate`, `select_option`, `check`, `uncheck`, `hover`, `dblclick`, `drag_to`
- [ ] Output `events.json` with normalized timestamps relative to video start
- [ ] Handle multi-page traces and iframes
- [ ] CLI: `docgen trace-extract [--test test_name] [--output events.json]`
- [ ] Unit tests for trace parsing with fixture trace files

### Issue 2: Playwright Test Runner Integration (`playwright_test_runner.py`)
- [ ] New runner that invokes `pytest` (or `playwright test`) with `--video on --tracing on` flags
- [ ] Discover and collect video + trace artifacts from test output directories
- [ ] Support filtering by test name/path to capture specific tests as segments
- [ ] Auto-detect Playwright config (`playwright.config.ts`, `conftest.py`) and video output paths
- [ ] Support both Python (`pytest-playwright`) and Node.js (`@playwright/test`) test frameworks
- [ ] Handle test failures gracefully — capture video even if assertions fail
- [ ] Config: `playwright_test:` block in `docgen.yaml` with `test_command`, `test_dir`, `video_dir`, `trace_dir`

### Issue 3: Event-to-Narration Synchronizer (`playwright_sync.py`)
- [ ] Load `events.json` (from trace extraction) + `timing.json` (from Whisper)
- [ ] Match narration anchors to video events by configured mapping or fuzzy keyword matching
- [ ] Compute per-segment speed adjustment factors (analogous to `tape_sync.py` window distribution)
- [ ] Generate `sync_map.json` mapping narration timestamps → video timestamps
- [ ] Support configurable sync strategies: `stretch` (adjust video speed), `cut` (trim idle), `pad` (freeze on key frames)
- [ ] CLI: `docgen sync-playwright [--segment 03] [--dry-run] [--strategy stretch]`
- [ ] Validation: warn when events and narration are mismatched in count or order

### Issue 4: Video Speed Adjustment via FFmpeg (`playwright_compose.py`)
- [ ] Apply `setpts` filter to speed up/slow down video segments to match narration timing
- [ ] Support piece-wise speed adjustment (different rates for different event windows)
- [ ] Preserve video quality during retiming (re-encode at source quality)
- [ ] Handle audio stripping from source video (Playwright videos may have no audio, or system audio)
- [ ] Integrate with existing `Composer._compose_simple` for final audio muxing
- [ ] Add `type: playwright_test` handler in `compose.py`

### Issue 5: Config & Visual Map Extensions
- [ ] Add `playwright_test:` configuration block to `Config` dataclass
- [ ] New config properties: `playwright_test_command`, `playwright_test_dir`, `playwright_test_video_dir`, `playwright_test_trace_dir`, `playwright_test_framework` (`pytest` or `playwright`)
- [ ] Extend `visual_map` to support `type: playwright_test` with fields: `test`, `source`, `trace`, `events` (anchor mappings)
- [ ] Add `sync_playwright_after_timestamps` pipeline option (analogous to `sync_vhs_after_timestamps`)
- [ ] Update `docgen.yaml` schema documentation
- [ ] Update `docgen init` scaffolding to offer Playwright test integration option

### Issue 6: Pipeline Integration
- [ ] Add `playwright_test` stages to `Pipeline.run()`: test execution → trace extraction → sync → compose
- [ ] Add `--skip-playwright-tests` flag to `docgen generate-all`
- [ ] Retry logic: if test fails, optionally retry once before skipping segment
- [ ] Support mixed pipelines: some segments from Manim, some from VHS, some from Playwright tests
- [ ] Order-of-operations: tests run after TTS + timestamps (need timing data for sync), before compose

### Issue 7: Auto-Discovery of Existing Playwright Tests
- [ ] Scan project for `conftest.py` with `playwright` imports, or `playwright.config.ts`
- [ ] Suggest visual_map entries based on discovered test files
- [ ] `docgen wizard` integration: show discovered tests as candidate segments in the setup GUI
- [ ] `docgen init` integration: auto-populate visual_map when Playwright tests are found
- [ ] Handle monorepo layouts where tests live in a different directory than docs

### Issue 8: Narration Anchor Auto-Detection
- [ ] Analyze Playwright actions (selectors, URLs, typed text) to suggest narration keywords
- [ ] Cross-reference with narration text to auto-map events to spoken words
- [ ] Use Whisper word-level timestamps for precise alignment
- [ ] Fallback: evenly distribute events across narration duration when no anchors match
- [ ] CLI: `docgen suggest-anchors --segment 03` to preview auto-detected mappings

### Issue 9: Validation Extensions
- [ ] Extend `Validator` to check `playwright_test` segments for A/V drift
- [ ] Validate that event count in trace matches expected narration anchor count
- [ ] OCR validation on Playwright test video (reuse existing `_ocr_scan`)
- [ ] Check for test failures in trace data and warn/fail appropriately
- [ ] Add `playwright_test` segment type to `--pre-push` checks

### Issue 10: Documentation & Dogfood
- [ ] Add Playwright test integration guide to README
- [ ] Convert one docgen e2e test (`test_setup_view.py` or `test_api_integration.py`) into a demo segment
- [ ] Add example `visual_map` entry using `type: playwright_test` in `docs/demos/docgen.yaml`
- [ ] Update milestone spec link in README
- [ ] Write a narration script that describes the wizard workflow, synced to the e2e test video

## Event-to-Audio Sync: Detailed Algorithm

The core synchronization algorithm (Issue 3) works as follows:

```
Input:
  events[] = [{t: 1.2, action: "fill"}, {t: 3.4, action: "click"}, ...]
  timing   = {segments: [{start: 0, end: 4.5, text: "..."}], words: [...]}
  anchors  = [{narration_anchor: "fill in email", action: "fill", selector: "#email"}, ...]

Algorithm:
  1. For each anchor, find the matching event in events[] by action + selector
  2. For each anchor, find the matching word/segment in timing by fuzzy text match
  3. Compute desired_time[i] = timing match timestamp for anchor i
  4. Compute actual_time[i]  = event timestamp for anchor i
  5. Build speed segments between consecutive anchor pairs:
     speed_factor[i] = (desired_time[i+1] - desired_time[i]) / (actual_time[i+1] - actual_time[i])
  6. Clamp speed factors to [0.25, 4.0] to avoid extreme distortion
  7. Generate ffmpeg filter: setpts with piece-wise PTS adjustment
  8. Apply filter to produce retimed video

Output:
  sync_map.json with per-anchor timing + retimed video file
```

This is conceptually identical to how `tape_sync.py` distributes narration duration across VHS blocks, but operates on continuous video rather than discrete Sleep directives.

## Integration into Existing Projects

For projects already using Playwright tests, the integration path is:

1. `pip install docgen` (or add to dev dependencies)
2. `docgen init` → detects existing Playwright tests, suggests visual_map entries
3. Write narration Markdown for each test-as-segment
4. `docgen generate-all` → runs tests with video+tracing, extracts events, syncs, composes
5. Demo videos are produced using actual app recordings from real tests

No changes to existing tests are required. The only new artifact is `docgen.yaml` configuration.

## Dependencies

- Playwright trace format documentation (stable since Playwright 1.12+)
- `zipfile` stdlib for trace.zip parsing
- `ffmpeg` `setpts` filter for speed adjustment (already a dependency)
- Existing docgen infrastructure: `Config`, `Composer`, `Validator`, `Pipeline`

## Risks

- **Trace format stability**: Playwright's internal trace format may change between versions. Mitigation: pin to trace format v3+ and version-detect.
- **Video quality**: Playwright test videos are typically low framerate (may be 5-10 FPS in CI). Mitigation: configurable upscale/interpolation via ffmpeg `minterpolate`.
- **Test flakiness**: Flaky tests produce inconsistent videos. Mitigation: retry logic + deterministic test fixtures.
- **Timing precision**: Browser rendering introduces variable delays. Mitigation: tolerance windows in anchor matching + clamp speed factors.
