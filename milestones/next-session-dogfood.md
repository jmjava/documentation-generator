# Next session — in-repo dogfood (documentation-generator on itself)

**In-repo** = this repository’s **`docs/demos`** tree. For a **second repo** that installs docgen as a library, see **[upstream dogfood](upstream-dogfood.md)**.

Goal: **`docs/demos`** exercises the **new** paths (catalog, discovery, `narration_from_source`, optional `playwright_test` compose) and you can run **`docgen generate-all`** (or a defined subset) end-to-end with documented prerequisites, then **`validate --pre-push`** green.

Work in order; stop and checkpoint when a step is big enough to ship alone.

---

## 0 — Preconditions (one-time check)

- [ ] Machine (or CI self-hosted runner) has: **Manim**, **ffmpeg**, **ttyd**, **xvfb** (or real display), **Playwright** if you capture fresh video, **`OPENAI_API_KEY`** for TTS / narration-generate.
- [ ] From repo root: `cd docs/demos` and `docgen --config docgen.yaml validate --help` loads.

---

## 1 — Wire dogfood `docgen.yaml` to new features

- [ ] Add **`discover_tests`** (and **`roots`**, if not only `.`) under `docs/demos/docgen.yaml` so `docgen discover-tests` matches this monorepo.
- [ ] Add **`narration_from_source`** (context paths, hints, model) pointing at real files (`README.md`, `AGENTS.md`, small `src/` snippets) so `docgen narration-generate --segment …` is meaningful.
- [ ] Run **`docgen catalog init`** at **repo root** (or set `catalog.file` in demos yaml); confirm **`docgen catalog stale`** behavior on a clean tree.

---

## 2 — One `playwright_test` segment in demos (minimal slice)

- [ ] Produce a **short pre-recorded** `.webm` (or `.mp4`) from a trivial Playwright test or reuse an existing artifact; place it under **`docs/demos/terminal/rendered/`** (or repo-relative path compose already resolves).
- [ ] Add **one new segment** (e.g. `07`) in `segments` / `segment_names` / `concat` and a **`visual_map`** entry `type: playwright_test` with `test` id + `source` path; keep existing 01–06 on Manim/VHS so the rest of the demo still works.
- [ ] **`pipeline.py`**: today only Manim + VHS render stages run before compose — add handling so **`playwright_test`** segments **skip** capture stages (or **sync** pre-recorded file into expected layout) so `generate-all` does not assume Manim/VHS for that segment. *(This is the main engineering chunk; align with checklist Phase C.)*

---

## 3 — Narration + catalog loop on real content

- [ ] **`docgen narration-generate --segment 07`** (or chosen id) **dry-run** then write; review `narration/*.md`.
- [ ] **`docgen discover-tests --merge-catalog`** (from repo root with config) if you want catalog entries for Node tests; **`docgen catalog refresh`** after edits.

---

## 4 — Full pipeline run

- [ ] From **`docs/demos`**: run **`docgen tts`** (or **`generate-all`** with explicit **`--skip-*`** flags if you want to iterate: e.g. skip Manim once visuals exist).
- [ ] Fix any **compose** / **freeze guard** issues for the new segment (audio vs video length).
- [ ] **`docgen validate`** then **`docgen validate --pre-push`** until clean (or document acceptable warnings).

---

## 5 — Close the loop in docs

- [ ] Update **`docs/demos`** README or top-of **`docgen.yaml`** comments with the **exact command sequence** you used for dogfood.
- [ ] Check off or adjust **[checklist-playwright-auto-narration.md](checklist-playwright-auto-narration.md)** Phase C “Dogfood” line once one `playwright_test` segment is real in-tree.

---

## Optional stretch

- [ ] **`docgen pages`** / GitHub Pages dry run for demos output.
- [ ] Wizard **UI** path: discovery → pick test → narrate (after API is stable enough).
