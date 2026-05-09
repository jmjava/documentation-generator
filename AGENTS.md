# Agent context — documentation-generator (`docgen`)

## North star

Stable goals for this repo and how it plugs into the wider suite:

1. **Embeddable generator** — **`pip install docgen`**, a `docgen.yaml`, and shell/CI are enough to build and maintain demos. **No IDE assistant (Cursor, Copilot, …) is required**; optional **`docgen wizard`** is a local web app only.
2. **Hybrid config and prose** — **`docgen.yaml`** should stay maintainable: **deterministic merges / discovery** (e.g. `yaml-generate` defaults, gap checks) plus **optional OpenAI** where it adds value (narration hints, scene/yaml prose). Prefer **Git-reviewed** changes over opaque single-shot generation.
3. **Two video surfaces** — **Long-form “how the system works”:** Markdown + TTS + **Manim** (+ **Playwright** in `visual_map` when the story needs a real browser). **Short tutorials from tests:** **Playwright** (`demo-function`, `discover-tests`, catalog). **VHS / `kind: cli`** is **legacy** and **may be deprecated**; do not start new work on tapes.
4. **Stable contracts** — CLI, exit codes, **`docgen.catalog.yaml`** at repo root, and reusable workflows should stay predictable so **other repos’ CI and Tekton** can depend on them without forking behavior.
5. **In-repo dogfood first** — Before treating **integrated apps** (`courseforge/course-builder`, etc.) as the primary focus, keep **`docs/demos`** honest: **`docgen --config docgen.yaml validate --pre-push`** from **`docs/demos`** must pass on **main** (same commands as any consumer). Full **`generate-all`** when changing pipeline or visuals. Tracker: **`milestones/next-session-dogfood.md`**.
6. **Tool-only generation** — Narration, merged **`docgen.yaml`**, scenes, TTS audio, composed media, catalog updates, and other **generated** artifacts must come from **docgen** (CLI/library) and **committed wrapper scripts** that call it—not from IDE-authored rewrites of outputs. If something cannot be done yet, **change docgen** (or add a small script) and then run the tool. For **`docs/demos`**, **`docgen.yaml`** is the **only** bundle config (same as any consumer): update it in Git, then **`docgen yaml-generate`** for defaults and **`manim_scene_generation` ↔ `visual_map` sync**—not a parallel maintainer-only YAML. Cursor rules: **`.cursor/rules/docgen-tools-only.mdc`**, **`.cursor/rules/no-asset-edits.mdc`**.

## Protected assets (Cursor must not edit)

`docgen` + OpenAI are the **only** path that produces these — Cursor edits live in `src/docgen/**`, `tests/**`, wrapper scripts, and rules/AGENTS. Full classification in **`.cursor/rules/no-asset-edits.mdc`**:

- **Outputs (Cursor MUST NOT edit):** `docs/demos/docgen.yaml`; `docs/demos/narration/*.md` (excluding `README.md`); `docs/demos/animations/scenes.py`, `docs/demos/animations/timing.json`, `docs/demos/animations/specs/*.scene.yaml` (declarative scene specs from **`docgen scene-spec-generate`** or hand-curated after generation; compiled into `scenes.py` via **`docgen scene-compile`**); `docs/demos/audio/*.mp3`; `docs/demos/recordings/**`.
- **Inputs / fixtures (Cursor edits OK; never deleted by reset):** `docs/demos/hints/**` (maintainer hint files for narration/scene LLM commands; wire via `context.paths` in `docgen.yaml`); `docs/demos/terminal/*.tape`; `docs/demos/scripts/*.py`; `fixtures/**` (raw Playwright specs there are inputs to `docgen per-function-generate`); `docs/demos/narration/README.md`.
- **Outputs (Cursor must NOT edit; emitted by docgen + OpenAI):** ...; `docs/demos/per-function/*.docgen.yaml` and sibling `*.html` (owner: `docgen per-function-generate`).

`docgen` itself contains **no hardcoded segment numbers, scene class names, tape filenames, or fixture paths**. Wiring is discovered: segments from `narration/`, tapes from `terminal/`, Playwright capture from `scripts/*.py` matched by segment id, Manim classes from `animations/scenes.py`, and Playwright project dirs (for `discover_tests.roots`) from `package.json` Playwright deps or `playwright.config.{js,ts,mjs,cjs}`. Tests may keep concrete ids and class names as test data.

**How this repo fits others:** **`courseforge/course-builder`** owns application code, manifests, and workflows that **invoke** docgen. **`courseforge/infrastructure`** owns **when** jobs run, secrets, Tekton/`jmjava/tekton-dag` wiring, and **org docs publishing** toward **`courseforge.github.io`**. **`jmjava/documentation-generator`** (here) owns **the implementation** of segment and per-function video pipelines. End-to-end publishing may span those repos; the **generator code** stays centralized here. Deeper suite narrative: **`courseforge/infrastructure`** → `docs/suite-integration.md`. In-repo dogfood vs upstream consumer: **`milestones/next-session-dogfood.md`**, **`milestones/upstream-dogfood.md`**.

### One-time: migration cleanup (related repos)

After a **large refactor** (north star, new Playwright/Manim focus, workflow layout, catalog contract), maintainers may do a **single coordinated pass** in **sibling repos**—for example **`courseforge/course-builder`** (workflow paths, per-function layout, pin comments) and **`courseforge/infrastructure`** (canonical pin in `docs/tekton-dag-reuse.md`, Tekton task defaults). That **structural** cleanup is **not** repeated on every docgen refresh; it pays down the cost of the refactor **once** (or when contracts change again in a big way).

### Consumer “full docgen reset” (repeatable)

There is **no** `docgen nuke-consumer` command. When a consumer is already on the **current layout** and you only need to **realign outputs and metadata** after bumping docgen or editing sources, use this **repeatable** playbook:

1. **Config** — From the bundle dir: `docgen --config … yaml-generate [--dry-run]` → review diff (defaults merge; optional `--llm`; comments not preserved). Optionally `yaml-generate --list-gaps` for narration vs `segments.all`.
2. **Catalog** — **`docgen catalog reset -y`** (empty all entries, keep file/schema) when discovery ids changed; or **`DOCGEN_CATALOG_FORCE_ALL=1`** for one run to treat every entry as stale without wiping the list.
3. **Outputs** — Full **`generate-all`** / per-function rebuilds + CI or local regen; delete or overwrite **`recordings/`**, **`audio/`**, **`per-function`**, caches per repo policy. For **this repository’s** `docs/demos` bundle, use **`docs/demos/_full-reset-regenerate.sh`** (automates catalog reset, deletion of regenerable paths, `generate-all`, `_rebuild-per-function.sh`, `validate --pre-push`; see **`docs/demos/README.md`**).
4. **CI / Pages** — **`workflow_dispatch`** or push; restore any curated files docgen overwrites (e.g. **`pages.yml`**).

**Pin bumps** (`pip install …@<sha>`) are **routine** when you adopt a new docgen commit; they are **not** the same as the one-time sibling-repo cleanup above.

Concrete **course-builder** notes: **`milestones/upstream-dogfood.md`**. Friction → **issues/PRs here**.

## What this repo is

`docgen` is the **documentation / narrated demo video engine**: CLI + library focused on **Manim** (long-form explanation) and **Playwright** (short tutorials from real UI tests). **VHS** (terminal `.tape`) is **legacy** and **may be deprecated**; it remains only for existing bundles and CI until migration. It is **not** the product app and **not** the CI orchestrator.

### Two pillars (keep product framing aligned)

- **Story mode** — **Manim**-forward long segments; optional **Playwright** in `visual_map`; **no new VHS**.
- **Truth-from-tests mode** — **Playwright** (`demo-function`, discovery). **`kind: cli`** (VHS) is legacy; same deprecation outlook as long-form tapes.

## CLI-first (no IDE assistant required)

Consuming repos should be able to bootstrap and maintain demos using **only** the published toolchain: `pip install docgen`, a `docgen.yaml`, shell/CI, and (where needed) `OPENAI_API_KEY`. **Cursor, Copilot, and other editor-integrated assistants are optional** and must not be assumed.

Typical commands (see repo `README.md` for flags): `docgen init`, `docgen yaml-generate`, `docgen narration-generate`, `docgen scene-generate`, **`docgen scene-spec-generate`** (LLM emits YAML only), **`docgen scene-compile`** (YAML → `scenes.py`), `docgen demo-function`, `docgen discover-tests`, `docgen catalog`, `docgen generate-all`, plus `tts`, `manim`, `compose`, **`concat`**, `validate`, … (**`vhs` / `sync-vhs`** = legacy). **`docgen wizard`** is an optional **local Flask web UI** in your browser, not an IDE plugin.

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

## Testing (downstream relevance)

**Downstream** here means **any project that uses docgen to generate documentation and demo assets** (narration, videos, pages, catalogs—not arbitrary unrelated apps). Tests in this repo should **cover what those consumers depend on**, not only internal refactors. Prioritize **stable contracts** and **CLI-visible behavior** that match **`docs/demos` dogfood** importer parity (**`docgen.yaml`** + **`yaml-generate`**, then same CLI as consumers): **`yaml-generate`**, **`scene-generate`**, **`scene-spec-generate`**, **`scene-compile`**, **`validate`** (streams, drift, manim lint, playwright_test), **`discover-tests`** / **catalog**, **`demo-function`**, **compose**, **`concat`**, **pages**, **`init`** scaffolding, **config** (`repo_root`, `discover_tests` roots), and **package exports**. Use **small fixtures** that hit the **same code paths** as real bundles; **`docs/demos`** is the full dogfood tree, not a pytest prerequisite. **Legacy VHS** tests may remain until migration but should not absorb most new coverage. When adding a feature adopters are expected to use, add or extend tests that would fail if that contract regresses in a downstream CI job.
