# docgen demo videos (dogfood)

This tree is the **in-repo dogfood** bundle: same **`docgen.yaml`** + CLI workflow as any downstream repo (paths relative to this directory unless noted).

Use **one** path below—they are **not** combined in a single session:

### A. Greenfield (no `docgen.yaml` yet, or you intend to replace it)

1. **`docgen init .`** — interactive **terminal** wizard (segments, paths, TTS).  
   *Or* **`docgen init . --defaults`** — same scaffold, no prompts (scripts/CI).
2. **`docgen --config docgen.yaml yaml-generate`** (or **`./_regenerate-docgen-config.sh`**) — merge tool defaults; (**re)build **`visual_map`** only from assets that **already exist** on disk (tapes, scripts, `*Scene` classes)—**never** invented placeholders (unless **`discovery.auto_visual_map: false`** and you edit by hand).
3. Then **`scene-spec-generate`** / **`scene-compile`** (preferred for diagram rows) or **`scene-generate`**, **`generate-all`**, **`validate`**, etc. as needed.

Do **not** open the browser wizard until step 1–2 exist; **`docgen wizard`** is not a substitute for **`docgen init`**.

### B. Day-to-day (this directory already has a valid `docgen.yaml`)

- **`docgen yaml-generate`**, pipeline commands, **`discover-tests`**, … as usual.
- **`docgen --config docgen.yaml wizard`** — optional **browser** UI only for iterating on narration; it assumes config is already there.

## Prerequisites

Full **`docgen generate-all`** for this bundle needs the toolchain that matches what is on disk after discovery:

- **`OPENAI_API_KEY`** — narration, TTS, optional scene/yaml prose.
- **Manim** + **ffmpeg** — for any segment whose `visual_map` type is `manim` (i.e. has a `class …Scene` in **`animations/scenes.py`**).
- **VHS** stack (**`vhs`**, **`ttyd`**, plus **Xvfb** or a display) — for any segment with a matching **`terminal/<stem>.tape`**.
- **Python Playwright** (**`pip install playwright`** + **`playwright install chromium`**) and any local toolchain the capture script invokes (e.g. **Node** with **`npm ci`** if a Playwright fixture under **`fixtures/`** runs **`npm run dev`**) — for any segment with a matching **`docs/demos/scripts/<segment-id>*.py`** capture driver.

`docgen yaml-generate` discovers which combination applies to the segments currently on disk; nothing is hardcoded per segment number.

## `visual_map` (in `docgen.yaml`)

**`visual_map`** is the per-segment block that names the video pipeline (Manim scenes, VHS tapes, or Playwright capture scripts) and each segment’s output filename.

- **`docgen init`** only writes structure (dirs, scripts, empty **`visual_map`**). It does **not** read tapes, capture scripts, or **`scenes.py`**, and does **not** embed **`manim:`** (or other visual-tool blocks)—those appear after **`docgen yaml-generate`** when discovery syncs Manim-related **`visual_map`** rows (or when you edit **`docgen.yaml`**). If **`manim`** is still absent, **`Config`** supplies defaults at runtime.
- **`docgen yaml-generate`** (**`--merge-defaults`**) maps each segment when **`terminal/<stem>.tape`**, a matching **`scripts/*.py`**, or the next **`class …Scene`** in **`animations/scenes.py`** is present; segments with none of those stay **unmapped** until you add assets and re-run (or set **`discovery.auto_visual_map: false`** and edit **`visual_map`** yourself).
- The same command syncs **`manim.scenes`** and **`manim_scene_generation.segments`** from Manim rows in **`visual_map`**.
- **`docgen discover-tests`** can emit suggested YAML for **`playwright_test`**-style rows (**`--suggest-visual-map`**, **`--write-suggest-visual-map`**); merge those in if you use catalog-driven segments.

## Declarative Manim (`animations/specs/*.scene.yaml`)

For segments whose `visual_map` type is **`manim`** and the story is mostly **rows of labeled `_box` diagrams**, prefer the **scene spec** path over raw **`scene-generate`** Python:

1. **`docgen scene-spec-generate --segment <ID> [--compile] [--hint "…"]`** — OpenAI emits **YAML only**; layout is compiled deterministically (every row `next_to` / `VGroup.arrange`). Writes **`animations/specs/<segment_stem>.scene.yaml`** by default; **`--compile`** injects into **`animations/scenes.py`**.
2. **`docgen scene-compile path/to/spec.scene.yaml`** — compile an existing spec (hand-edited or from the LLM) without another API call.
3. Then **`docgen timestamps`** (if you use Whisper alignment), **`docgen manim`**, **`docgen compose`**, and **`docgen concat full-demo`** when refreshing recordings.

Optional YAML overrides for the LLM system prompt: `manim_scene_generation.scene_spec_system_prompt` (root or per-segment). Schema and compiler: `docgen.scene_spec` in source.

**`scene-generate`** remains available when you need full Manim freedom (transforms, custom mobjects) and accept higher layout risk from model-authored Python.

## Full reset (total nuke + regen)

**`_full-reset-regenerate.sh`** automates a **full** dogfood regen:

1. **`docgen clean-bundle -y --reset-catalog --delete-config --keep-narration`** — removes **`docgen.yaml` first**, then clears generated assets (see **`docgen clean-bundle --help`**). **`--keep-narration`** keeps **`narration/*.md`** so **`docgen init --defaults`** can reinfer **`segments`** from filenames.
2. **`docgen init . --defaults`** — writes a fresh **`docgen.yaml`** scaffold (empty **`visual_map`** until **`yaml-generate`**).
3. **`docgen yaml-generate`** — merge tool defaults / skeletons.
4. OpenAI **`narration-generate`** / **`scene-spec-generate`** (or **`scene-generate`**), **`generate-all`**, per-function rebuild, **`validate --pre-push`**, **`_seed-examples.sh`**.

For a **generic** wipe (any repo): run **`docgen --config /path/to/docgen.yaml clean-bundle -y`** with or without **`--delete-config`** / **`--keep-narration`**.

**Removed by clean-bundle:** segment narration (unless **`--keep-narration`**), **`animations/`**, **`audio/*.mp3`**, **`terminal/`** (recreated with **`rendered/`**), **`recordings/*.mp4`** and **`recordings/per-function/`**, **`.docgen-state.json`**, and catalog entries when **`--reset-catalog`**. With **`--delete-config`**, **`docgen.yaml`** is removed first.

**Preserved:** **`narration/README.md`**, **`per-function/*.docgen.yaml`** and **`*.html`**, repo-root **`fixtures/`**. Run **`docgen yaml-generate`** after **`init`** so **`visual_map`** matches tapes, scripts, and Manim scenes on disk.

```bash
cd docs/demos
./_full-reset-regenerate.sh
```

## Commands (typical)

**Greenfield (pick one init style):**

```bash
cd docs/demos
docgen init .              # interactive terminal wizard — scaffold when starting from nothing
docgen init . --defaults   # non-interactive scaffold (scripts/CI); mutually exclusive with prompts above
docgen --config docgen.yaml yaml-generate
# Nuke config + outputs (generic): docgen --config docgen.yaml clean-bundle -y --delete-config [--keep-narration] [--no-reset-catalog]
```

**Already have `docgen.yaml` — optional browser UI for narration only:**

```bash
cd docs/demos
docgen --config docgen.yaml wizard    # http://127.0.0.1:8501 — do not use instead of init
```

**Inspect CLI:**

```bash
cd docs/demos
docgen --config docgen.yaml validate --help
```

Source-catalog metadata (repo root; shared with other workflows):

```bash
cd docs/demos
docgen --config docgen.yaml catalog init         # once; creates ../../docgen.catalog.yaml
docgen --config docgen.yaml catalog stale
```

Discovery and catalog merge (when a Playwright project is present under the repo, `docgen init` will already have added it to `discover_tests.roots`):

```bash
# Install whichever Playwright fixture(s) the repo ships under fixtures/<name>/.
# `docgen init` autodetects them via package.json (@playwright/test/playwright)
# or playwright.config.{js,ts,mjs,cjs}.
docgen --config docgen.yaml discover-tests
docgen --config docgen.yaml discover-tests --merge-catalog
docgen --config docgen.yaml catalog refresh
```

Drafting narration for any segment (requires `OPENAI_API_KEY`):

```bash
cd docs/demos
docgen --config docgen.yaml narration-generate --segment <ID> --dry-run
docgen --config docgen.yaml narration-generate --segment <ID>
```

Full pipeline (heavy):

```bash
cd docs/demos
docgen --config docgen.yaml generate-all
# or iterate with skips, e.g. --skip-tts after audio exists
```

Per-function micro-demos (`docgen demo-function`) live under `per-function/` and are
rebuilt by `_rebuild-per-function.sh`. Each manifest's URL placeholder
(`file://__FIXTURE__/...`) is rewritten to a real `file://` path before invocation.
TTS is mandatory: the script aborts with exit code 2 if `OPENAI_API_KEY` is missing.

```bash
cd docs/demos
./_rebuild-per-function.sh
ls recordings/per-function/   # <slug>.mp4 alias + <slug>/ artifact tree
```

The rendered MP4 is surfaced on the pages site via `pages.per_function` in
`docgen.yaml`. Long-form walkthroughs of the same subcommand are produced by
`docgen generate-all` like any other segment.

Validation:

```bash
cd docs/demos
docgen --config docgen.yaml validate
docgen --config docgen.yaml validate --pre-push
```

Upstream consumer dogfood (separate clone) is described in `milestones/upstream-dogfood.md` at the repo root.

Any **Playwright** fixture under `fixtures/` is exercised in CI (see `.github/workflows/ci.yml`).
