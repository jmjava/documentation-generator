# docgen — documentation generator

Reusable Python library and CLI for **narrated demo videos** built around **Manim**,
**OpenAI TTS**, and **ffmpeg** composition. Aimed at long-form, scripted explainers
that walk through how a system works.

## Suite handbook (Courseforge)

Prose + **PlantUML** sources for how Courseforge repositories fit together live under **`docs/suite/`**. Regenerate PNGs with `./scripts/render-suite-diagrams.sh` — **Java**, **Graphviz** (`dot`), and the vendored JAR in **`third_party/plantuml/`** (CI installs Graphviz and runs the same script; see `.github/workflows/render-suite-diagrams.yml`). The rendered site at **courseforge.github.io** pulls this tree on each publish from **courseforge/infrastructure**.

## What changed: Playwright is gone

`docgen` no longer ships any Playwright-driven UI demo path. The previous
`demo-function`, `playwright`, `discover-tests`, `vhs`, `tape-lint`, `sync-vhs`,
`per-function-*`, and `catalog` commands — together with their config blocks
(`vhs:`, `playwright:`, `playwright_test:`, `discover_tests:`, `catalog:`,
`per_function:`) and the `playwright`, `playwright_test`, and `vhs` `visual_map`
types — have been **removed**.

Why: a UI-test-driven recorder turned out to be a fragile, project-specific concern
that pulled `pytest-playwright`, Node Playwright, VHS / `ttyd`, browser binaries,
trace parsing, and a discovery catalog into a generic library. The same goal is now
being prototyped in a consumer project (CourseForge `tools/courseforge/demogen/`)
with the “LLM emits a validated automation spec, a deterministic runner translates
it to Playwright” pattern. Once that contract stabilises a small portion may be
backported into `docgen`, but `docgen` itself stays Playwright-free.

If you still need the legacy behaviour, pin a pre-removal commit
(`pip install docgen @ git+https://github.com/jmjava/documentation-generator.git@<sha>`).

## What docgen does today

- **TTS narration** — generate MP3 audio from Markdown scripts via OpenAI
  `gpt-4o-mini-tts`.
- **Word-level timestamps without Whisper** — the default `local` engine aligns
  the known narration text against the TTS mp3 offline (ffmpeg `silencedetect`
  + proportional interpolation); no API call or transcription. OpenAI
  `whisper-1` remains available via `timestamps.engine: whisper` /
  `docgen timestamps --engine whisper`. Both engines write the same
  `timing.json` shape.
- **Manim animations** — primary visual surface. Use **`docgen scene-spec-generate`**
  + **`scene-compile`** (or hand-maintained **`animations/specs/*.scene.yaml`**)
  for deterministic diagram layout: rows are auto-paginated when they exceed the
  frame stack budget, specs that overflow safe width / budget are rejected, and
  (when `timing.json` carries Whisper words) each row’s first label is mapped to
  a **`wait_word`** index. Hand-maintained custom Manim classes still live in
  `animations/scenes.py` outside the `BEGIN/END GENERATED SCENE` markers.
- **OpenAI image assets in Manim scenes** — a scene-spec box may be an **image
  element** (`image: images/<name>.png` + `prompt:`); `docgen image-generate`
  renders the prompt via the OpenAI Images API (default `gpt-image-1`) and the
  compiled scene shows it with the `_image` helper (`ImageMobject`, `Group`
  rows). `generate-all` fills in missing assets automatically.
- **ffmpeg composition** — combine narration audio and Manim video into final
  segments, with a freeze-tail guard.
- **Validation** — A/V drift, freeze ratio, OCR error scan, layout, narration lint,
  Manim scene lint, **timing_sync** (stale `timing.json` vs regenerated mp3 —
  hard fail), and **av_sync** (OCR check that spoken anchor keywords appear on
  screen near their spoken time — soft warning).
- **GitHub Pages** — auto-generate `index.html`, deploy workflow, LFS rules,
  `.gitignore`.
- **Wizard** — local web GUI to bootstrap narration scripts from existing project
  docs.

**No IDE lock-in:** maintenance workflows are `docgen` CLI + YAML + shell/CI (and
OpenAI where a command calls the API). The wizard is a local Flask app, not a
plugin tied to one editor.

## Install

```bash
pip install docgen @ git+https://github.com/jmjava/documentation-generator.git
```

## Development setup

```bash
git clone https://github.com/jmjava/documentation-generator.git
cd documentation-generator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

CI installs `ffmpeg` and `tesseract` via apt — see `.github/workflows/ci.yml`.

**Roadmap:** [milestones/README.md](milestones/README.md).

## Quick start

```bash
cd your-project/docs/demos
docgen wizard              # optional: bootstrap narration from project docs
docgen generate-all        # TTS → timestamps → scene retime → Manim → compose → validate
docgen validate --pre-push
```

## CLI commands

| Command | Description |
|---------|-------------|
| `docgen init [TARGET_DIR] [--defaults] [--segments-file FILE]` | Scaffold a new project: `docgen.yaml`, wrapper scripts, directories |
| `docgen wizard [--port 8501]` | Local web GUI: focus files, **revise narration in place**, asset freshness chips, **rebuild-from-here** (default cascade: TTS → timestamps → scene-retime → Manim → compose → validate; LLM scene-spec is explicit) |
| `docgen tts [--segment 01] [--dry-run]` | Generate TTS audio |
| `docgen timestamps [--engine local\|whisper]` | Extract word/segment timestamps from TTS audio → `timing.json` (default `local`: offline narration-text alignment; `whisper`: OpenAI transcription) |
| `docgen image-generate [--segment 01 \| --all \| --spec PATH] [--force] [--dry-run] [--model …] [--size …]` | Generate scene-spec image assets (`image:` + `prompt:` boxes) via the OpenAI Images API into the bundle |
| `docgen manim [--scene StackDAGScene]` | Render Manim animations |
| `docgen compose [01 02 03] [--ffmpeg-timeout 900]` | Compose segments (audio + video) |
| `docgen validate [--max-drift 2.75] [--pre-push]` | Run all validation checks |
| `docgen lint [--segment 01]` | Narration lint only |
| `docgen concat [--config full-demo]` | Concatenate full demo files |
| `docgen pages [--force]` | Generate `index.html`, `pages.yml`, `.gitattributes`, `.gitignore` |
| `docgen generate-all [--skip-tts] [--skip-manim] [--retry-manim] [--regen-scene-specs]` | Full pipeline: TTS → timestamps → **scene retime** (existing specs) → Manim → compose → validate. `--regen-scene-specs` also runs OpenAI scene-spec-generate |
| `docgen rebuild-after-audio [--regen-scene-specs]` | Timestamps → scene retime → Manim → compose → validate (skips TTS) |
| `docgen clean-bundle [-y] [--delete-config] [--keep-narration]` | Remove regenerable outputs under the bundle |
| `docgen narration-generate --segment 01 [--extra-path REL] [--hint TEXT] [--dry-run] [--force]` | Generate narration `.md` from repo sources + owner hints (OpenAI); see `narration_from_source` in YAML |
| `docgen yaml-generate [--merge-defaults] [--llm] [--dry-run] [--list-gaps]` | Merge defaults into `docgen.yaml`; optional OpenAI refresh of `tts.instructions` / `wizard.system_prompt` (rewrites the file — review in Git) |
| `docgen scene-compile [SPEC.scene.yaml \| --all] [--retime] [--dry-run]` | Compile declarative scene YAML into `animations/scenes.py`. **`--all --retime`** re-derives `wait_word` from current `timing.json` with no OpenAI; unmatched labels fail closed (or set `pace: none`) |
| `docgen scene-spec-generate [--segment 01 \| --all] [--compile] [--print-only] [--output PATH] [--hint …] [--model …]` | Call OpenAI to emit YAML only (same schema as `scene-compile`); rejects frame-budget overflow and **subject-beat coverage** failures (hold board on same topic; cover topic shifts; no invented labels — not a blind count); auto-paginate + word-alignment; optionally writes `animations/specs/<stem>.scene.yaml` and `--compile`s into `scenes.py` |

## Configuration

Create a `docgen.yaml` in your demos directory. Use **`docgen init`** to scaffold
a fresh layout, then **`docgen yaml-generate`** to fill in defaults from the files
already on disk. (`docgen yaml-generate` also keeps
`manim_scene_generation.segments` in step with `visual_map`.)

The **`visual_map`** key is maintainer-owned per-segment wiring. Supported types
are `manim`, `mixed`, `still`, and `image`.

### `env_file` and the shell

If `docgen.yaml` sets `env_file` (often `.env`), variables are loaded with
**shell-first** semantics: anything already exported in the process (including
your IDE or CI) is **not** replaced by the file. To make the file win, set
**`DOCGEN_ENV_OVERRIDES=1`** so every key from `env_file` overwrites the
environment, or **`DOCGEN_ENV_OVERRIDES=OPENAI_API_KEY,OTHER_KEY`** for specific
keys only.

When `OPENAI_API_KEY` is present in both the shell and `env_file`, docgen prints a
one-line hint to stderr so a silent 401 from the wrong key is easier to diagnose.

### Narration from source (owner hints)

Under `narration_from_source` in `docgen.yaml`, the **project owner** lists
optional `hints` (strings) that steer the model (audience, terminology, what to
avoid). OpenAI generates the narration `.md` from your repo context
(`context.paths` / `context.globs`, relative to `repo_root`) plus those hints; the
result is what `docgen tts` reads. See `docgen.narrate_from_source`.

```yaml
narration_from_source:
  model: gpt-4o-mini
  temperature: 0.65
  max_context_bytes: 120000
  hints:
    - "Audience: contributors new to this repo."
    - "Do not mention unreleased product codenames."
  context:
    paths:
      - README.md
    globs:
      - "src/**/*.py"
  segments:
    "01":
      hints:
        - "This segment covers the install wizard only."
      context:
        paths:
          - docs/install.md
```

### Useful pipeline options

```yaml
validation:
  max_drift_sec: 2.75
  max_freeze_ratio: 0.25     # trailing-frame pad vs narration length (compose freeze guard + validate)
  timing_sync:               # audio ↔ timing.json staleness (hard fail in --pre-push)
    enabled: true
    max_tail_gap_sec: 3.0    # mp3 may run this much past the last transcribed word
    max_end_overrun_sec: 1.0 # transcript may extend this far past the mp3
  av_sync:                   # OCR anchor check (soft warning in --pre-push)
    enabled: true
    tolerance_sec: 3.0
    visual_types: [manim]    # only check types with on-screen text

timestamps:
  engine: local              # local (default, offline) or whisper (OpenAI whisper-1)
  silence_noise_db: -35.0    # ffmpeg silencedetect threshold for the local engine
  min_silence_sec: 0.3

image_generation:            # scene-spec image elements (docgen image-generate)
  model: gpt-image-1
  size: 1536x1024
  # quality: high            # optional, model-specific

manim:
  quality: 1080p30           # supports 480p15, 720p30, 1080p30, 1080p60, 1440p30, 1440p60, 2160p60
  manim_path: ""             # optional explicit binary path (relative to docgen.yaml or absolute)
  font: "Liberation Sans"
  min_font_size: 14

validation:
  subject_beat_coverage:
    enabled: true            # scene-spec-generate + validate: cover narration topic beats

compose:
  ffmpeg_timeout_sec: 300    # can also be overridden with: docgen compose --ffmpeg-timeout N
```

## System dependencies

- **ffmpeg** — composition and probing
- **tesseract-ocr** — OCR validation
- **Manim** — primary visuals (optional install: `pip install docgen[manim]`)

## Milestone spec

See [milestone-doc-generator.md](https://github.com/jmjava/tekton-dag/blob/main/milestones/milestone-doc-generator.md)
for the full design document.
