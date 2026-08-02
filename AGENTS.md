# Agent context — documentation-generator (`docgen`)

## North star

Stable goals for this repository:

1. **Embeddable generator** — **`pip install docgen`** (git URL or editable install from this repo), a consumer **bundle** (`docgen.yaml` + hints/narration), and shell/CI are enough to build and maintain narrated demos. **Do not vendor** this library into a product repo’s `src/`; pin via `requirements-docgen.txt` / `pipx` / `uv tool`. **No IDE assistant is required**; optional **`docgen wizard`** is a local web app only.
2. **Hybrid config and prose** — **`docgen.yaml`** should stay maintainable: deterministic merges (**`yaml-generate`**, gap checks) plus **optional OpenAI** where it adds value (narration hints, declarative scene YAML). Prefer **Git-reviewed** changes over opaque single-shot generation.
3. **Video stack** — Long-form demos pair **Markdown narration**, **OpenAI TTS**, **Whisper-style timestamps**, **Manim** visuals, **`compose`** (ffmpeg), **`concat`**, and **`validate`** (sync and narration lint). The CLI also supports **`pages`** for static preview sites.
4. **Stable contracts** — CLI, exit codes, and reusable workflows should stay predictable for downstream repos and automation.
5. **Library, not app** — There is **no in-repo dogfood bundle**. Consumer projects (e.g. `course-builder`) are the integration test of record. The library must not import or special-case any consumer.
6. **Tool-only generation** — Narration, merged **`docgen.yaml`**, compiled **`scenes.py`**, TTS audio, composed media, and other **generated** artifacts must come from **docgen** (CLI/library) and **committed wrapper scripts** that call it — not from hand-edited outputs passed off as sources. In a consumer bundle, prefer **`hints/*.md`** + **`yaml-generate`** over ad-hoc YAML surgery. Cursor rules: **`.cursor/rules/docgen-tools-only.mdc`**, **`.cursor/rules/no-asset-edits.mdc`**.

## Protected assets in a consumer bundle (Cursor must not edit)

`docgen` + OpenAI are the **only** path that produces category **C** outputs — see **`.cursor/rules/no-asset-edits.mdc`**. Summary (paths relative to a consumer bundle, typically `docs/demos/`):

- **Outputs (do not hand-edit):** `<bundle>/docgen.yaml` (as emitted by **`yaml-generate`**); `<bundle>/narration/*.md` (except `README.md`); `<bundle>/animations/scenes.py`, `timing.json`, `animations/specs/*.scene.yaml` (scene pipeline); `<bundle>/audio/*.mp3`; `<bundle>/images/*.png` (scene image assets from **`image-generate`**); `<bundle>/recordings/**` where applicable.
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
- **`wizard`** — local web UI for narration/bootstrap workflows (focus files, **in-place narration revise**, per-segment **asset freshness** + **rebuild-from-here**, **Tool** tab to pip-upgrade docgen and pin `requirements-docgen.txt`).
- **`tts`** — text-to-speech for segment files.
- **`timestamps`** — word/segment timing (`timing.json`). Default engine **`local`** aligns the known narration text against the mp3 offline (ffmpeg silencedetect, no API); **`--engine whisper`** keeps OpenAI whisper-1 transcription. Both emit the same Whisper-shaped blocks.
- **`image-generate`** — render scene-spec **image elements** (`image:` + `prompt:` boxes) via the OpenAI Images API into the bundle (also runs for missing assets inside `generate-all`).
- **`manim`** — render Manim scenes declared in config.
- **`compose`** — mux narration audio with visual sources via ffmpeg.
- **`validate`** / **`validate --pre-push`** — drift, narration lint, Manim hints, **`timing_sync`**, **`story_end`** (last paced reveal vs audio end; hard fail), **`av_sync`** (soft; prefers scene-spec labels as OCR anchors), **`subject_beat_coverage`** (declarative specs vs narration topic beats; hard fail when enabled), and related checks.
- **`lint`** — narration lint helper.
- **`narration-generate`** — LLM-assisted narration from hints and repo context; optional **`--revise --revision-notes`** for in-place edits (same contract as the wizard Revise button).
- **`scene-spec-generate`** — LLM emits declarative **`*.scene.yaml`**; enforces frame budget + **subject-beat coverage** (dwell OK; cover topic shifts; reject invented labels).
- **`scene-compile`** — compile specs into **`scenes.py`** (generated regions only).
- **`yaml-generate`** — merge defaults and hint wiring into **`docgen.yaml`**.
- **`clean-bundle`** — remove regenerable outputs per policy.
- **`concat`** — stitch segment videos.
- **`pages`** — emit static HTML for demo assets.
- **`generate-all`** — orchestrated pipeline: TTS → timestamps → **scene specs** (auto `scene-spec-generate` when `animations/specs/` is empty; otherwise offline retime) → images → Manim → compose → validate → concat → pages. `--regen-scene-specs` forces LLM rewrite; `--skip-scene-retime` keeps legacy hand `scenes.py` only.
- **`rebuild-after-audio`** — same as generate-all with TTS skipped (still retimes scenes after timestamps).

## Implications for changes here

- **Manim / `scenes.py` (marker blocks):** Fix generators under `src/docgen/**` (`manim_scene_support.py`, `scene_spec.py`, `scene_spec_generate.py`, `validate`, `yaml_generate`, tests). **Do not** patch generated classes inside a consumer's **`animations/scenes.py`** between **`BEGIN/END GENERATED SCENE`** markers; re-run **`scene-spec-generate`** / **`scene-compile --retime`** and **`manim`** instead. Preferred consumer order: narration → TTS → timestamps → scene-spec/compile → Manim → compose.
- **Beat sync (fail-closed):** when `timing.json` has words, every story box label must match a spoken phrase (`wait_word`); unmatched labels and leftover LLM indices are rejected. Opt out with ``pace: none``. Fuzzy containment matching is not used. **`scene-compile` clamps FadeIn / page-fade `run_time` against the next word start** so `_TimedScene._clock` cannot race past waits (issue #66 — do not emit cascading first-board dumps). Page transitions FadeOut revealed boxes, not the parent `VGroup`.
- **Subject-beat coverage:** implemented in `scene_spec.layout_density_violations` / `cluster_subject_beats`; enforced by **`scene-spec-generate`** and **`validate`** (`validation.subject_beat_coverage.enabled`, default true). Not a blind label count.
- Prefer **stable CLI / library contracts** and **documented exit codes** so CI can depend on them.
- **`narration_from_source`:** hints in config + **`docgen narration-generate`** — owner-supplied context paths, not opaque bulk edits to outputs.
- Avoid duplicating long orchestration docs here; **link** to downstream repos when describing their publish pipelines.

## Testing (downstream relevance)

Tests should cover **CLI-visible behavior** and contracts that adopters rely on: **`yaml-generate`**, **`scene-spec-generate`**, **`scene-compile`**, **`validate`**, **`compose`**, **`generate-all`**, **`pages`**, **`init`**, **config** loading (`repo_root`, `env_file`), and package exports. Use small in-tree fixtures; this library does not ship a dogfood bundle.

## Cursor Cloud specific instructions

- **Virtualenv:** the project is installed editable into **`/workspace/.venv`** (created by the startup update script). Shells do **not** auto-activate it — run `. /workspace/.venv/bin/activate` (or prefix the venv path) before `docgen`, `pytest`, or `ruff`. The `docgen` console script lives at `/workspace/.venv/bin/docgen`.
- **System deps are pre-baked in the VM snapshot** (not the update script): `ffmpeg` + `tesseract-ocr` (validation/compose/OCR), plus `build-essential`, `python3-dev`, `libcairo2-dev`, `libpango1.0-dev`, `pkg-config` (needed to build the `manim` extra's `manimpango`/`pycairo` wheels). If a fresh VM ever lacks these, reinstall via apt before `pip install`.
- **Standard commands** are in `README.md` / `pyproject.toml` / `.github/workflows/ci.yml`: lint `ruff check src/ tests/`; tests `pytest tests/ -v --tb=short`; the CI unit job also exports `PYTHONPATH=src` (not needed locally because of the editable install, but harmless).
- **OpenAI-gated vs offline commands:** `tts`, `timestamps --engine whisper`, `image-generate`, `narration-generate`, `scene-spec-generate`, and `yaml-generate --llm` call OpenAI and need `OPENAI_API_KEY` (integration tests auto-skip without it). Fully offline: `init`, `scene-compile`, `manim`, `compose`, `validate`, `lint`, `pages`, `concat`, `yaml-generate` (no `--llm`), and `timestamps` (default `local` engine).
- **`scene-compile` gotcha:** paced specs (`wait_word`) need a `timing.json` entry for that stem (`docgen timestamps` after TTS). Prefer `scene-compile --retime` after fresh timestamps; for a fully offline smoke render, author rows without wait indices only if you accept unpaced reveals.
- **No in-repo dogfood bundle:** exercise the pipeline against a scratch bundle (`docgen init /tmp/<name> --defaults` in a throwaway git dir). Do not hand-edit consumer generated assets (see `.cursor/rules/no-asset-edits.mdc`).
- **Wizard:** `docgen wizard --port 8501` is an optional local Flask app (long-lived); run it from a bundle directory that contains `docgen.yaml`.
