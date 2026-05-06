# Checklist — Playwright auto-discovery, Node-first, LLM narration

Goal: discover Playwright tests (Node primary, Python secondary), run or attach artifacts, generate narration markdown (OpenAI) from test + trace + repo context, and feed the existing docgen pipeline (`playwright_test` validators already exist; compose/runner still needed).

Use this as a working checklist; reorder within a phase as dependencies land.

---

## Foundation — catalog (stable path, incremental regeneration)

- [x] Default catalog path: **`<repo_root>/docgen.catalog.yaml`** (`Config.catalog_file_path`) so consuming projects commit one canonical file; optional `catalog.file` (relative to repo root or absolute).
- [x] Module `src/docgen/source_catalog.py`: schema v1, load/save, input fingerprints, `entry_needs_regeneration`, `merge_entries`, **`entry_should_run`**, **`parse_force_id_list` / `force_ids_from_env`**, **`policy.regenerate` pin + `clear_regenerate_pin`** (override + action-driven regen contract).
- [x] CLI: `docgen catalog init`, `docgen catalog stale`, `docgen catalog refresh` (writes/updates catalog on disk). Still TODO: fold discover into catalog; wire narrate/render to call `entry_should_run` + `catalog refresh` only after successful steps.

---

## Phase A — Node test discovery (ship first)

- [x] Detect Node Playwright: `playwright.config.*` + `@playwright/test` in `package.json` (`test_discovery.node_playwright_project_ready`).
- [x] List tests via `npx playwright test --list` (JSON if present, else line reporter) — `discover_node_playwright_tests`.
- [x] Stable ids + catalog entries — `NodePlaywrightTest.stable_id` / `catalog_entry()`; CLI `docgen discover-tests [--merge-catalog]`.
- [ ] Resolve app root(s) for monorepos beyond `--repo-root` (config `test_roots[]` default list).
- [ ] Read `webServer`, `baseURL`, artifact settings from Playwright config for doc defaults / LLM context.
- [ ] Emit suggested `visual_map` YAML snippets into stdout or a file (today: `NodePlaywrightTest.suggested_visual_map_snippet` exists but not wired to CLI).
- [ ] `docgen wizard` / `init` integration.
- [x] Unit tests: `tests/test_discovery.py`.

### Vite-oriented checks

- [ ] Default / docs: assume Vite dev server via `webServer` in Playwright config; do not hard-code port
- [ ] Document or detect `vite.config.*` only when useful for LLM context (optional)

---

## Phase B — Python test discovery (second)

- [ ] Detect `pytest-playwright` / `playwright` usage in `conftest.py` / deps
- [ ] Collect tests: `pytest --collect-only` or AST-assisted discovery for `page` fixture tests
- [ ] Same output shape as Node so `visual_map` and downstream steps stay unified
- [ ] Unit tests for Python fixture layout

---

## Phase C — `playwright_test` pipeline (video + compose)

- [ ] Implement runner: invoke tests with video + trace per segment (or consume CI-produced artifacts via paths in `docgen.yaml`)
- [x] `compose.py`: handle `vtype == "playwright_test"` — mux pre-recorded `source` with segment audio (`repo_root` path first, then `terminal/rendered/`). **Retiming from `sync_map` not implemented yet** (prints NOTE when sync_map present).
- [ ] `pipeline.py`: run Playwright-test stages when `visual_map` contains `playwright_test`
- [ ] Dogfood: one `visual_map` entry in this repo or `examples/` when stable
- [ ] Re-run / extend existing validator tests (`tests/test_validate_playwright.py`) against real-shaped artifacts

---

## Phase D — LLM narration from tests + codebase

- [x] **Owner hints + repo context → narration `.md`:** `docgen.narrate_from_source` + CLI `docgen narration-generate` (`narration_from_source` in `docgen.yaml`, OpenAI chat → `narration/<segment>.md`). Extend later with Playwright/trace-aware context packs.
- [ ] New module (e.g. `narrate_from_tests.py`): build **context pack** (capped tokens)
  - [ ] Test source (spec + one-hop imports)
  - [ ] Trace / events JSON when available (truncated, normalized)
  - [ ] Repo snippets: README, router/routes, components matching selectors / `data-testid` / `getByRole` strings
- [ ] Config block in `docgen.yaml`: model, limits, `context_globs`, redaction on/off
- [ ] Chat completion with **structured output** (JSON: `markdown`, optional `anchors` / `events` suggestions) then validate and write files
- [ ] CLI: e.g. `docgen narrate-tests` (names TBD) with `--dry-run`, `--segment`, `--test <id>`
- [ ] Redaction pass before API (secrets, emails in fixtures)
- [ ] Cache key on test source + trace hash to skip redundant calls

---

## Phase E — Wizard & init

- [ ] `docgen init`: optional scaffold when Playwright detected (suggested segments + placeholder narration)
- [ ] Wizard API + UI: list discovered tests → pick test → generate narration → preview → save
- [ ] Wire env / model from existing `env_file` and OpenAI patterns (`wizard.generate_narration_via_llm` style)

---

## Phase F — Hardening

- [ ] Docs: single “Node-first + Vite” authoring page (commands, config knobs, artifact paths)
- [ ] Cost / rate limits: retries, max context size, clear errors when trace missing for strict mode
- [ ] Pre-push / CI: document recommended `docgen validate` after generated narration

---

## References in this repo

- Issue sketch: `issues/playwright-test-integration/07-auto-discovery.md`
- Architecture / `visual_map`: `milestones/milestone-4-playwright-test-video.md`
- Validators: `src/docgen/validate.py` (`playwright_test_*`), `tests/test_validate_playwright.py`
- Node invoke precedent: `src/docgen/demo_function.py` (`npx playwright test`, sidecar manifests)
- Existing LLM narration pattern: `src/docgen/wizard.py` (`generate_narration_via_llm`)
