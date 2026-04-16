# Issue: Validation Extensions for Playwright Test Segments

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** Medium
**Depends on:** Issues 4, 5

## Summary

Extend the existing `Validator` to handle `playwright_test` segments, including A/V drift checks, event-narration alignment validation, OCR scanning, and test failure detection.

## Acceptance Criteria

- [ ] Extend `Validator` to check `playwright_test` segments for A/V drift (reuse existing `_check_av_drift`)
- [ ] Validate that event count in trace matches expected narration anchor count
- [ ] Warn when speed adjustment factors are extreme (< 0.25 or > 4.0)
- [ ] OCR validation on Playwright test video (reuse existing `_ocr_scan`)
- [ ] Check for test failures in trace data and warn/fail appropriately
- [ ] Verify that retimed video duration matches narration audio duration (within `max_drift_sec`)
- [ ] Add `playwright_test` segment type to `--pre-push` checks
- [ ] Report includes: test name, video source, sync quality metrics

## Files to Create/Modify

- **Modify:** `src/docgen/validate.py`
- **Create:** `tests/test_validate_playwright.py`
