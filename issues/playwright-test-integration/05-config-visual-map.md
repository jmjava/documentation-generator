# Issue: Config & Visual Map Extensions for playwright_test

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** Medium (enables pipeline)
**Depends on:** None (can be done in parallel)

## Summary

Extend `Config`, `docgen.yaml` schema, and `docgen init` to support the new `playwright_test` visual source type and its associated configuration.

## Acceptance Criteria

- [ ] Add `playwright_test:` configuration block to `Config` dataclass:
  ```yaml
  playwright_test:
    framework: pytest              # "pytest" or "playwright"
    test_command: ""               # custom test command override
    test_dir: tests/e2e/           # where tests live
    video_dir: test-results/videos/ # where Playwright saves videos
    trace_dir: test-results/traces/ # where Playwright saves traces
    retain_on_failure: true         # capture video even if test fails
    transcode_to_mp4: true          # convert WebM to MP4 at collection time
    default_viewport:
      width: 1920
      height: 1080
  ```
- [ ] New config properties: `playwright_test_framework`, `playwright_test_command`, `playwright_test_dir`, `playwright_test_video_dir`, `playwright_test_trace_dir`, etc.
- [ ] Extend `visual_map` to support `type: playwright_test`:
  ```yaml
  visual_map:
    "03":
      type: playwright_test
      test: tests/e2e/test_wizard.py::test_setup_flow
      source: test-results/videos/test_setup_flow.webm
      trace: test-results/traces/test_setup_flow/trace.zip
      events:
        - narration_anchor: "launch the wizard"
          action: goto
          url: /
        - narration_anchor: "select the setup tab"
          action: click
          selector: "[data-tab=setup]"
  ```
- [ ] Add `sync_playwright_after_timestamps` pipeline option (analogous to `sync_vhs_after_timestamps`)
- [ ] Update `docgen init` to offer Playwright test integration option when tests are detected
- [ ] Validate config: ensure referenced test files, video files, and trace files exist
- [ ] Unit tests for new config parsing

## Files to Create/Modify

- **Modify:** `src/docgen/config.py`
- **Modify:** `src/docgen/init.py` (if scaffolding updated)
- **Modify:** `tests/test_config.py`
