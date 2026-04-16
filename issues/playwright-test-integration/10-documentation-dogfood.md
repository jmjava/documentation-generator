# Issue: Documentation & Dogfood for Playwright Test Video

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** Medium
**Depends on:** Issues 1-6

## Summary

Document the Playwright test video integration and dogfood it by converting one of docgen's own e2e tests into a demo video segment.

## Acceptance Criteria

- [ ] Add Playwright test integration guide section to README:
  - Overview of the approach (reuse existing tests)
  - Configuration example (`docgen.yaml` with `type: playwright_test`)
  - Step-by-step walkthrough
  - Event anchor configuration reference
  - Sync strategy documentation
- [ ] Convert one docgen e2e test into a demo segment:
  - Candidate: `tests/e2e/test_setup_view.py` (wizard setup flow)
  - Add `type: playwright_test` entry to `docs/demos/docgen.yaml`
  - Write narration script for the wizard walkthrough synced to test events
- [ ] Update `docs/demos/docgen.yaml` with example `playwright_test` visual_map entry
- [ ] Update milestone spec link in README
- [ ] Add FAQ section: "When to use Playwright test vs custom Playwright script vs Manim vs VHS"

## Dogfood Plan

The docgen project already has these e2e tests that exercise the wizard:
- `test_setup_view.py` — navigates tabs, checks headings, verifies file tree
- `test_production_view.py` — switches to production view, tests narration editing
- `test_api_integration.py` — tests API endpoints (scan, generate, etc.)

The `test_setup_view.py::test_setup_tab_navigation` test is ideal for dogfooding:
1. It opens the wizard
2. Clicks through setup tabs
3. Verifies the file tree renders
4. These are exactly the actions a demo video would show

Narration would describe: "The wizard provides a local web interface for creating narration scripts. Let's walk through the setup flow — first we see the project overview, then select source documents..."

## Files to Create/Modify

- **Modify:** `README.md`
- **Modify:** `docs/demos/docgen.yaml`
- **Create:** `docs/demos/narration/07-wizard-demo.md` (narration for wizard test video)
