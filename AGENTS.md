# Agent context — documentation-generator (`docgen`)

## North star

Stable goals for this repository:

1. **Embeddable generator** — **`pip install docgen`** (or editable install from source), a `docgen.yaml`, and shell/CI are enough to build and maintain narrated demos. **No IDE assistant is required**; optional **`docgen wizard`** is a local web app only.
2. **Hybrid config and prose** — **`docgen.yaml`** should stay maintainable: deterministic merges (**`yaml-generate`**, gap checks) plus **optional OpenAI** where it adds value (narration hints, declarative scene YAML). Prefer **Git-reviewed** changes over opaque single-shot generation.
3. **Video stack** — Long-form demos pair **Markdown narration**, **OpenAI TTS**, **Whisper-style timestamps**, **Manim** visuals, **`compose`** (ffmpeg), **`concat`**, and **`validate`** (sync and narration lint). The CLI also supports **`pages`** for static preview sites.
4. **Stable contracts** — CLI, exit codes, and reusable workflows should stay predictable for downstream repos and automation.
5. **Library, not app** — There is **no in-repo dogfood bundle**. Consumer projects (e.g. `course-builder`) are the integration test of record. The library must not import or special-case any consumer.
6. **Tool-only generation** — Narration, merged **`docgen.yaml`**, compiled **`scenes.py`**, TTS audio, composed media, and other **generated** artifacts must come from **docgen** (CLI/library) and **committed wrapper scripts** that call it — not from hand-edited outputs passed off as sources. In a consumer bundle, prefer **`hints/*.md`** + **`yaml-generate`** over ad-hoc YAML surgery. Cursor rules: **`.cursor/rules/docgen-tools-only.mdc`**, **`.cursor/rules/no-asset-edits.mdc`**.

## Protected assets in a consumer bundle (Cursor must not edit)

`docgen` + OpenAI are the **only** path that produces category **C** outputs — see **`.cursor/rules/no-asset-edits.mdc`**. Summary (paths relative to a consumer bundle, typically `docs/demos/`):

- **Outputs (do not hand-edit):** `<bundle>/docgen.yaml` (as emitted by **`yaml-generate`**); `<bundle>/narration/*.md` (except `README.md`); `<bundle>/animations/scenes.py`, `timing.json`, `animations/specs/*.scene.yaml` (scene pipeline); `<bundle>/audio/*.mp3`; `<bundle>/recordings/**` where applicable.
- **Inputs (maintainer-owned):** `<bundle>/hints/**` with YAML front matter (`docgen.segment`, `docgen.wiring`); maintainer scripts under the bundle; `tests/**` fixtures inside this library; `<bundle>/narration/README.md`.

`docgen` avoids hardcoding consumer segment ids in library code; tests may use concrete fixtures.

### Consumer resets (generic)

Downstream repos that pin this library should:

1. Run **`docgen yaml-generate`** (and review the diff).
2. Regenerate narration, scenes, audio, and video with the documented CLI sequence for their bundle.
3. Run **`validate`** / **`validate --pre-push`** before pushing.

**Pin bumps** (`pip install …@<sha>`) are routine when adopting a new docgen commit.

## What this repo is

`docgen` is a **documentation and narrated demo video** toolkit: CLI + library focused on **Manim** (diagram-heavy segments), **TTS**, **timestamps**, **composition**, **validation**, **`pages`**, and **wizard**-assisted authoring. It is **not** the product application and **not** the CI orchestrator for downstream apps.

The Playwright/VHS/demo-function/per-function/discover-tests/catalog surface area was removed; see the README for what is supported today.

## CLI surface (today)

Commands registered on the **`docgen`** CLI include:

- **`init`** — scaffold bundle layout and `docgen.yaml`.
- **`wizard`** — local web UI for narration/bootstrap workflows.
- **`tts`** — text-to-speech for segment files.
- **`timestamps`** — align narration audio to Whisper-style word/segment timing (`timing.json`).
- **`manim`** — render Manim scenes declared in config.
- **`compose`** — mux narration audio with visual sources via ffmpeg.
- **`validate`** / **`validate --pre-push`** — drift, narration lint, Manim hints, and related checks.
- **`lint`** — narration lint helper.
- **`narration-generate`** — LLM-assisted narration from hints and repo context.
- **`scene-spec-generate`** — LLM emits declarative **`*.scene.yaml`**.
- **`scene-compile`** — compile specs into **`scenes.py`** (generated regions only).
- **`yaml-generate`** — merge defaults and hint wiring into **`docgen.yaml`**.
- **`clean-bundle`** — remove regenerable outputs per policy.
- **`concat`** — stitch segment videos.
- **`pages`** — emit static HTML for demo assets.
- **`generate-all`** — orchestrated pipeline for a bundle.
- **`rebuild-after-audio`** — rerun steps that depend on fresh audio/timing.

## Implications for changes here

- **Manim / `scenes.py` (marker blocks):** Fix generators under `src/docgen/**` (`manim_scene_support.py`, `scene_spec.py`, `scene_spec_generate.py`, `validate`, `yaml_generate`, tests). **Do not** patch generated classes inside a consumer's **`animations/scenes.py`** between **`BEGIN/END GENERATED SCENE`** markers; re-run **`scene-spec-generate`** / **`scene-compile`** and **`manim`** instead.
- Prefer **stable CLI / library contracts** and **documented exit codes** so CI can depend on them.
- **`narration_from_source`:** hints in config + **`docgen narration-generate`** — owner-supplied context paths, not opaque bulk edits to outputs.
- Avoid duplicating long orchestration docs here; **link** to downstream repos when describing their publish pipelines.

## Testing (downstream relevance)

Tests should cover **CLI-visible behavior** and contracts that adopters rely on: **`yaml-generate`**, **`scene-spec-generate`**, **`scene-compile`**, **`validate`**, **`compose`**, **`generate-all`**, **`pages`**, **`init`**, **config** loading (`repo_root`, `env_file`), and package exports. Use small in-tree fixtures; this library does not ship a dogfood bundle.
