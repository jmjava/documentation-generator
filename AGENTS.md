# Agent context — documentation-generator (`docgen`)

## What this repo is

`docgen` is the **documentation / narrated demo video engine**: CLI + library for manifests, Playwright-related capture, TTS, compose, validate, and publishing helpers. It is **not** the product app and **not** the CI orchestrator.

## Ecosystem (keep in focus)

| Piece | Role |
|-------|------|
| **`courseforge/course-builder`** | Product: pluggable **tool/library** being built. Owns app code and, typically, doc manifests / tests that docgen consumes. |
| **`courseforge/infrastructure`** | **Orchestration**: local Kind + Tekton, reuse of **`jmjava/tekton-dag`** for builds, pins to this repo, optional Tekton Tasks that invoke `docgen`, and **docs publishing** flow toward **`courseforge/github.io`**. |
| **`jmjava/documentation-generator`** (here) | **Generator**: features should remain **embeddable** (`pip install docgen`, `docgen.yaml`, clear CLI) so infrastructure and course-builder can call them without forking. |

Suite-level integration narrative (Phase 1 vs 2, GHA vs Tekton): see **`courseforge/infrastructure`** → `docs/suite-integration.md`.

## Implications for changes here

- Prefer **stable CLI / library contracts** and **documented exit codes** (e.g. neutral skip) so CI and Tekton steps can depend on them.
- **Playwright test discovery**, **LLM-authored narration**, and **`playwright_test`** pipeline behavior belong **in this repo**; wiring secrets, cache volumes, and “when to run” belong in **infrastructure** / **course-builder** workflows.
- **Discovery catalog:** default path is **`<repo_root>/docgen.catalog.yaml`** (`Config.catalog_file_path`) so every consuming repo has one stable, commit-friendly file for incremental regeneration; override with `catalog.file` in `docgen.yaml` if needed. Bundled issue template: **`docgen self catalog-issue-template`** (pip installs get it via `package-data`, not the git-only `docs/` tree).
- **Narration from source:** **`docgen narration-generate`** + YAML `narration_from_source` — project-owner **hints** (not model-generated) plus repo file context; OpenAI writes narration `.md` for **`docgen tts`** (`docgen.narrate_from_source`).
- Avoid duplicating long orchestration docs here; **link** to infrastructure or course-builder when describing publish pipelines.
