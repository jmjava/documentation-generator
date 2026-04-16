# Issue: Pipeline Integration for Playwright Tests

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** Medium
**Depends on:** Issues 1-5

## Summary

Integrate the Playwright test runner, trace extractor, and sync engine into the docgen pipeline (`generate-all`, `rebuild-after-audio`).

## Acceptance Criteria

- [ ] Add Playwright test stages to `Pipeline.run()`:
  1. (existing) TTS → Timestamps
  2. (new) Run Playwright tests → Collect videos + traces
  3. (new) Extract events from traces
  4. (new) Sync events to narration timing
  5. (existing) Manim, VHS, Compose, Validate, Concat, Pages
- [ ] Order of operations: tests run after TTS + timestamps (need timing data for sync), before compose
- [ ] Add `--skip-playwright-tests` flag to `docgen generate-all`
- [ ] Retry logic: if test fails, optionally retry once before skipping segment
- [ ] Support mixed pipelines: some segments from Manim, some from VHS, some from Playwright tests
- [ ] Pipeline only runs Playwright test stages if any `visual_map` entry has `type: playwright_test`

## Technical Notes

Pipeline flow with Playwright tests:

```python
def run(self, ..., skip_playwright_tests: bool = False):
    # ... TTS, Timestamps, VHS sync (existing) ...

    if not skip_playwright_tests and self._has_playwright_test_segments():
        print("\n=== Stage: Playwright Tests ===")
        from docgen.playwright_test_runner import PlaywrightTestRunner
        runner = PlaywrightTestRunner(self.config)
        runner.run_tests()

        print("\n=== Stage: Trace Extraction ===")
        from docgen.playwright_trace import TraceExtractor
        TraceExtractor(self.config).extract_all()

        if self.config.sync_playwright_after_timestamps:
            print("\n=== Stage: Sync Playwright ===")
            from docgen.playwright_sync import PlaywrightSynchronizer
            PlaywrightSynchronizer(self.config).sync()

    # ... Manim, VHS, Compose, Validate, Concat, Pages (existing) ...
```

## Files to Create/Modify

- **Modify:** `src/docgen/pipeline.py`
- **Modify:** `src/docgen/cli.py` (add `--skip-playwright-tests` flag)
- **Create:** `tests/test_pipeline_playwright.py`
