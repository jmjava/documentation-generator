# Example bundle (leftover — not the integration test of record)

This tree is a **leftover in-repo example** of a consumer bundle layout (`docgen.yaml` + hints + narration). The library **no longer ships dogfood**; downstream repos are the integration test of record — see **[`milestones/upstream-dogfood.md`](../../milestones/upstream-dogfood.md)**.

Composed MP4s land under **`recordings/`** here when someone still runs the pipeline locally. That is **not** a product repo’s **`docs/rendered/`** tree (Courseforge Pages aggregation).

Use **one** path below—they are **not** combined in a single session:

### A. Greenfield (no `docgen.yaml` yet, or you intend to replace it)

1. **`docgen init .`** — interactive **terminal** wizard (segments, paths, TTS).  
   *Or* **`docgen init . --defaults`** — same scaffold, no prompts (scripts/CI).
2. **`docgen --config docgen.yaml yaml-generate`** (or **`./_regenerate-docgen-config.sh`**) — merge tool defaults; (re)build **`visual_map`** from **`animations/scenes.py`**, hint wiring, and assets that already exist on disk — **never** invented placeholders (unless **`discovery.auto_visual_map: false`** and you edit by hand).
3. Then **`scene-spec-generate`** / **`scene-compile`**, **`generate-all`**, **`validate`**, etc. as needed.

Do **not** open the browser wizard until step 1–2 exist; **`docgen wizard`** is not a substitute for **`docgen init`**.

### B. Day-to-day (this directory already has a valid `docgen.yaml`)

- **`docgen yaml-generate`**, pipeline commands, … as usual.
- **`docgen --config docgen.yaml wizard`** — optional **browser** UI only for iterating on narration; it assumes config is already there.

## Prerequisites

Full **`docgen generate-all`** for this bundle needs:

- **`OPENAI_API_KEY`** — narration, TTS, optional scene-spec prose.
- **Manim** + **ffmpeg** — for segments whose `visual_map` type is **`manim`** (a `class …Scene` in **`animations/scenes.py`**).

`docgen yaml-generate` discovers Manim segments from **`animations/scenes.py`** and hint wiring; nothing terminal- or tape-based is used in this bundle.

**Note:** If you edit `narration/*.md`, run **`docgen tts`** and **`docgen timestamps`** when you want **`animations/timing.json`** (including Whisper **words** / **segments**) to match the new spoken audio. Until then, timing data may still mention older phrasing even though maintainer-facing prose is updated.

## `visual_map` (in `docgen.yaml`)

**`visual_map`** names the video source per segment (**Manim** in this bundle).

- **`docgen init`** writes structure only. **`docgen yaml-generate`** (**`--merge-defaults`**) aligns **`visual_map`** with **`animations/scenes.py`** (and hint wiring where present).
- The same command syncs **`manim.scenes`** and **`manim_scene_generation.segments`** from Manim rows in **`visual_map`**.

Historic **Playwright** / **demo-function** / **per-function** capture paths were **removed** from the library (see root **`AGENTS.md`**); do not expect browser-test recording commands in current `docgen`.

## Declarative Manim (`animations/specs/*.scene.yaml`) — **default**

This is the **default** visual path for all consumers (not optional decoration):

1. First **`docgen generate-all`** (or **`scene-spec-generate --all --compile`**) writes
   **`animations/specs/<stem>.scene.yaml`** and injects generated classes into
   **`animations/scenes.py`** between marker comments.
2. Later **`generate-all`** / **`rebuild-after-audio`** **retime-compiles** those specs
   against fresh **`timing.json`** (no OpenAI) so beat sync stays correct.
3. Force a layout rewrite with **`--regen-scene-specs`**. Skip the stage only for
   legacy hand scenes: **`--skip-scene-retime`**.

Label boxes with **spoken phrases from the narration** (must match `timing.json`
words), keep ~3 rows/page, and follow **`hints/manim-scene-specs.md`**.

## Full reset (total nuke + regen)

**`_full-reset-regenerate.sh`** automates a **full** regen of this leftover example (see script header for exact steps): essentially **`clean-bundle`**, **`init`**, **`yaml-generate`**, then OpenAI-backed **`narration-generate`** / **`scene-spec-generate --all --compile`**, **`generate-all`**, and **`validate --pre-push`**.

```bash
cd docs/demos
./_full-reset-regenerate.sh
```

**Removed by clean-bundle** includes segment narration (unless **`--keep-narration`**), **`animations/`**, **`audio/*.mp3`**, **`recordings/*.mp4`**, etc. **Preserved:** **`narration/README.md`** and maintainer **`hints/**`**.

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
