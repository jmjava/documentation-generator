# docgen demo videos (dogfood)

This tree is the **in-repo dogfood** bundle: same **`docgen.yaml`** + CLI workflow as any downstream repo (paths relative to this directory unless noted).

Use **one** path below—they are **not** combined in a single session:

### A. Greenfield (no `docgen.yaml` yet, or you intend to replace it)

1. **`docgen init .`** — interactive **terminal** wizard (segments, paths, TTS).  
   *Or* **`docgen init . --defaults`** — same scaffold, no prompts (scripts/CI).
2. **`docgen --config docgen.yaml yaml-generate`** (or **`./_regenerate-docgen-config.sh`**) — merge tool defaults; (re)build **`visual_map`** from assets that **already exist** on disk (VHS tapes, `*Scene` classes in **`animations/scenes.py`**)—**never** invented placeholders (unless **`discovery.auto_visual_map: false`** and you edit by hand).
3. Then **`scene-spec-generate`** / **`scene-compile`**, **`generate-all`**, **`validate`**, etc. as needed.

Do **not** open the browser wizard until step 1–2 exist; **`docgen wizard`** is not a substitute for **`docgen init`**.

### B. Day-to-day (this directory already has a valid `docgen.yaml`)

- **`docgen yaml-generate`**, pipeline commands, … as usual.
- **`docgen --config docgen.yaml wizard`** — optional **browser** UI only for iterating on narration; it assumes config is already there.

## Prerequisites

Full **`docgen generate-all`** for this bundle needs:

- **`OPENAI_API_KEY`** — narration, TTS, optional scene-spec prose.
- **Manim** + **ffmpeg** — for segments whose `visual_map` type is **`manim`** (a `class …Scene` in **`animations/scenes.py`**).
- **VHS** stack (**`vhs`**, **`ttyd`**, plus **Xvfb** or a display) — only if you still ship matching **`terminal/<stem>.tape`** segments (legacy; not required for the default Manim-only demos here).

`docgen yaml-generate` discovers which combination applies from what is on disk; nothing is hardcoded per segment number.

**Note:** If you edit `narration/*.md`, run **`docgen tts`** and **`docgen timestamps`** when you want **`animations/timing.json`** (including Whisper **words** / **segments**) to match the new spoken audio. Until then, timing data may still mention older phrasing even though maintainer-facing prose is updated.

## `visual_map` (in `docgen.yaml`)

**`visual_map`** names the video source per segment (today: **Manim** scenes, or legacy **VHS** tapes).

- **`docgen init`** writes structure only. **`docgen yaml-generate`** (**`--merge-defaults`**) maps segments when **`terminal/<stem>.tape`** or the next **`class …Scene`** in **`animations/scenes.py`** is present.
- The same command syncs **`manim.scenes`** and **`manim_scene_generation.segments`** from Manim rows in **`visual_map`**.

Historic **Playwright** / **demo-function** / **per-function** capture paths were **removed** from the library (see root **`AGENTS.md`**); do not expect browser-test recording commands in current `docgen`.

## Declarative Manim (`animations/specs/*.scene.yaml`)

For **`manim`** segments built from labeled `_box` diagrams:

1. **`docgen scene-spec-generate --segment <ID> [--compile] [--hint "…"]`** — optional OpenAI emits **YAML**; **`--compile`** injects into **`animations/scenes.py`**. Use **`--all --compile`** for every declarative segment.
2. **`docgen scene-compile path/to/spec.scene.yaml`** — compile a spec without another API call.
3. Then **`docgen timestamps`**, **`docgen manim`**, **`docgen compose`**, and **`docgen concat full-demo`** when refreshing recordings.

Run **`docgen timestamps`** after changing narration audio so **`timing.json`** gains **`words`** / segments required by **`wait_segment`** / **`wait_word`** in specs.

## Full reset (total nuke + regen)

**`_full-reset-regenerate.sh`** automates a **full** dogfood regen (see script header for exact steps): essentially **`clean-bundle`**, **`init`**, **`yaml-generate`**, then OpenAI-backed **`narration-generate`** / **`scene-spec-generate --all --compile`**, **`generate-all`**, and **`validate --pre-push`**.

```bash
cd docs/demos
./_full-reset-regenerate.sh
```

**Removed by clean-bundle** includes segment narration (unless **`--keep-narration`**), **`animations/`**, **`audio/*.mp3`**, **`recordings/*.mp4`**, etc. **Preserved:** **`narration/README.md`**, maintainer **`hints/**`**, repo-root **`fixtures/`** per bundle policy.

## Commands (typical)

**Greenfield:**

```bash
cd docs/demos
docgen init .
docgen --config docgen.yaml yaml-generate
```

**Inspect / validate:**

```bash
cd docs/demos
docgen --config docgen.yaml validate
docgen --config docgen.yaml validate --pre-push
```

**Narration (requires `OPENAI_API_KEY`):**

```bash
cd docs/demos
docgen --config docgen.yaml narration-generate --segment <ID> --dry-run
docgen --config docgen.yaml narration-generate --segment <ID>
```

**Full pipeline:**

```bash
cd docs/demos
docgen --config docgen.yaml generate-all
# or iterate with skips, e.g. --skip-tts after audio exists
```

After changing **hints** under **`hints/`**, run **`docgen yaml-generate`** before TTS or scene work so **`docgen.yaml`** wiring stays merged.

Upstream consumer dogfood is described in **`milestones/upstream-dogfood.md`** at the repo root.
