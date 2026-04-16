# Issue: Auto-Discovery of Existing Playwright Tests

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** Low (nice-to-have)
**Depends on:** Issues 2, 5

## Summary

Automatically discover existing Playwright tests in a project and suggest `visual_map` entries, both during `docgen init` and in the wizard GUI.

## Acceptance Criteria

- [ ] Scan project for Playwright indicators:
  - Python: `conftest.py` with `playwright` imports, `pytest-playwright` in dependencies
  - Node.js: `playwright.config.ts` or `playwright.config.js`, `@playwright/test` in `package.json`
- [ ] Discover individual test files and test functions
- [ ] Suggest `visual_map` entries based on discovered tests:
  ```
  Found 3 Playwright tests:
    tests/e2e/test_setup_view.py::test_setup_tab_navigation
    tests/e2e/test_setup_view.py::test_bulk_generate
    tests/e2e/test_api_integration.py::test_scan_endpoint

  Suggested visual_map entries:
    "03": { type: playwright_test, test: "tests/e2e/test_setup_view.py::test_setup_tab_navigation" }
    "04": { type: playwright_test, test: "tests/e2e/test_setup_view.py::test_bulk_generate" }
  ```
- [ ] `docgen wizard` integration: show discovered tests as candidate segments in the setup GUI
- [ ] `docgen init` integration: auto-populate visual_map when Playwright tests are found
- [ ] Handle monorepo layouts where tests live in a different directory than docs
- [ ] CLI: `docgen discover-tests [--dir tests/]`

## Files to Create/Modify

- **Create:** `src/docgen/test_discovery.py`
- **Modify:** `src/docgen/wizard.py` (add test discovery API)
- **Modify:** `src/docgen/init.py` (integrate discovery into scaffolding)
- **Modify:** `src/docgen/cli.py` (add `discover-tests` command)
- **Create:** `tests/test_discovery.py`
