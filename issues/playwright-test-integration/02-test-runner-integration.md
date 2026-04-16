# Issue: Playwright Test Runner Integration

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** High (foundational)
**Depends on:** None (parallel with Issue 1)

## Summary

Create `playwright_test_runner.py` — a runner that invokes existing Playwright test suites with video and tracing enabled, then collects the resulting video and trace artifacts for use as docgen visual sources.

## Background

The existing `PlaywrightRunner` in `playwright_runner.py` runs custom capture scripts specifically written for docgen. This new runner takes a fundamentally different approach: it runs the project's **existing** Playwright tests as-is, enabling video recording and tracing via Playwright configuration, and harvests the artifacts.

This supports both Python (`pytest-playwright`) and Node.js (`@playwright/test`) test frameworks.

## Acceptance Criteria

- [ ] Invoke `pytest` or `npx playwright test` with `--video on --tracing on` flags
- [ ] Auto-detect test framework from project files (`conftest.py` → pytest, `playwright.config.ts` → Node.js)
- [ ] Discover and collect video + trace artifacts from test output directories
- [ ] Support filtering by test name/path to capture specific tests as segments
- [ ] Auto-detect video output paths from Playwright config
- [ ] Handle test failures gracefully — capture video even if assertions fail (using `--tracing retain-on-failure` or equivalent)
- [ ] Config block in `docgen.yaml`:
  ```yaml
  playwright_test:
    framework: pytest          # or "playwright" for Node.js
    test_command: "pytest tests/e2e/ --video on --tracing on"
    test_dir: tests/e2e/
    video_dir: test-results/videos/
    trace_dir: test-results/traces/
    retain_on_failure: true
  ```
- [ ] CLI command: `docgen playwright-test [--test test_login.py] [--timeout 300]`

## Technical Notes

### pytest-playwright video config

```python
# conftest.py
@pytest.fixture(scope="session")
def browser_context_args():
    return {"record_video_dir": "test-results/videos/"}
```

Or via CLI: `pytest --video on --tracing on`

### @playwright/test video config

```typescript
// playwright.config.ts
export default defineConfig({
  use: {
    video: 'on',
    trace: 'on',
  },
});
```

The runner should inject these settings via environment variables or config overrides without requiring users to modify their test configuration permanently.

## Files to Create/Modify

- **Create:** `src/docgen/playwright_test_runner.py`
- **Modify:** `src/docgen/config.py` (add `playwright_test` config properties)
- **Modify:** `src/docgen/cli.py` (add `playwright-test` command)
- **Create:** `tests/test_playwright_test_runner.py`
