## Summary

Implement (or extend) CI so **`docgen.catalog.yaml`** at the **repository root** drives **incremental** narration/render: skip entries whose input fingerprints match the catalog, **unless** an override applies. The catalog file should only be updated in an **explicit** workflow step after a successful regen (action-driven), not as a side effect of unrelated jobs.

**Upstream reference:** [`jmjava/documentation-generator`](https://github.com/jmjava/documentation-generator) — `Config.catalog_file_path`, module `docgen.source_catalog` (`entry_should_run`, `refresh_entry_fingerprints`, `save_catalog`, `force_ids_from_env`, `policy.regenerate` / `clear_regenerate_pin`). README § *Discovery catalog*.

---

## For the **application / docs repo** (where `docgen.yaml` lives)

### 1. Pin docgen

- [ ] Install `docgen` from a **pinned git SHA** or release (same pattern as `courseforge/infrastructure` docs today).
- [ ] Ensure the pinned version includes **`source_catalog`** APIs (or bump pin after merge).

### 2. Commit the catalog

- [ ] Add **`<repo_root>/docgen.catalog.yaml`** to git (default path; override with `catalog.file` in `docgen.yaml` if required).
- [ ] Initial file can be an empty `entries: []` scaffold until `docgen discover-tests` / wizard writes real rows.

### 3. GitHub Actions workflow shape

- [ ] **Checkout** with history if you diff against `main` for changed manifests/tests.
- [ ] **Install** docgen + system deps (ffmpeg, Playwright browsers, etc.) per segment types you use.
- [ ] One-time or CI bootstrap: `docgen catalog init` (creates `docgen.catalog.yaml` at repo root when missing).
- [ ] **Discover / select work** (when CLI exists): merge discovery into catalog, or build candidate entry list.
- [ ] **For each catalog entry** (or each changed test): call logic equivalent to `entry_should_run(entry, repo_root, global_force=…, force_ids=…)`:
  - Pass **`DOCGEN_CATALOG_FORCE_IDS`** from `workflow_dispatch` inputs or matrix (comma-separated entry ids) for ad-hoc forced regen **without** editing YAML.
  - Respect **`policy.regenerate: true`** on an entry for “must regen on next green run”; clear pin after success via `clear_regenerate_pin` + commit.
- [ ] **Regenerate** only entries that should run (narration, TTS, capture, compose as applicable).
- [ ] **On success only:** run `docgen catalog refresh` (and `--clear-pins` if you use `policy.regenerate`) so fingerprints on disk match sources, then **commit** the catalog (and rendered assets) in the same job or a follow-up “docs commit” step with a clear condition (`github.ref == refs/heads/main` vs PR artifacts only). Equivalent library calls: `refresh_entry_fingerprints` + `save_catalog`.

### 4. PR vs `main`

- [ ] **Pull requests:** upload rendered previews + catalog diff as **artifacts** (or bot comment); avoid committing catalog churn to every PR unless that is intentional.
- [ ] **`main` (or release branch):** commit updated `docgen.catalog.yaml` + published paths so the next run skips unchanged entries.

### 5. Secrets and cost

- [ ] **`OPENAI_API_KEY`** (or org secret) for LLM/TTS when used.
- [ ] Optional: cache directory for `docgen demo-function` / heavy stages (align with infrastructure `docgen-sync-spec` § caching).

---

## For **`courseforge/infrastructure`** (orchestration only)

Skip this section if the issue is filed in the app repo only.

- [ ] Document in **`docs/suite-integration.md`** (or equivalent) how **aggregator** / cross-repo publish interacts with per-repo **`docgen.catalog.yaml`** (each source repo owns its catalog; no central merge unless explicitly designed).
- [ ] Optional: add a **reusable workflow** or doc snippet that consuming repos `uses:` so catalog env vars (`DOCGEN_CATALOG_FORCE_IDS`) and “commit on main” pattern stay consistent.

---

## Acceptance criteria

- A **no-op** CI run (no source changes, no overrides) skips heavy regen for catalog entries whose **fingerprints** still match.
- **`workflow_dispatch`** (or similar) can force specific **entry ids** via **`DOCGEN_CATALOG_FORCE_IDS`** without a catalog YAML edit.
- A maintainer can set **`policy.regenerate: true`** on one catalog entry and have the **next** successful pipeline regen that entry and **clear** the pin in the committed catalog.
- Catalog **mtime/content** updates only from the **designated** “regen + refresh catalog” path, not from unrelated jobs.

---

## Open upstream work (track separately)

- [ ] `docgen discover-tests` + merge into catalog.
- [ ] `docgen catalog status` (human-friendly listing; optional `--json` for CI).
- [ ] Narrate/render commands that call `entry_should_run` and `docgen catalog refresh` only after successful per-entry work.
