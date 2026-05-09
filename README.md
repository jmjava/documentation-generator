# docgen — documentation generator

Reusable Python library and CLI for **narrated demo videos**, focused on **Manim** (long-form stories) and **Playwright** (tutorials from UI tests). **VHS** terminal tapes are **legacy** and **may be deprecated**.

# Video documentation for this project was generated with the library
https://jmjava.github.io/documentation-generator/

## Two pillars

1. **Long-form narrative** (`docgen generate-all` and friends) — explain **how a system works**: scripted narration, **Manim** as the main visual, optional **Playwright** capture in `visual_map` where the story needs a real browser, then **ffmpeg** composition. **Do not start new work on VHS** (`.tape` terminal recordings): that stack is **legacy** and **may be deprecated**; prefer Manim for terminal-ish stories (simulated output, diagrams) or migrate segments to Playwright/Manim.
2. **Playwright tutorial mode** (`docgen demo-function`, `docgen discover-tests`) — turn **existing Playwright UI tests** (or YAML that mirrors them) into **one short MP4 per scenario**, with TTS and captions.

**VHS (terminal tapes)** — **`docgen vhs`**, **`sync-vhs`**, **`tape-lint`**, and **`demo-function`** `kind: cli` remain for **existing projects and CI** until a deprecation window is announced. **New demos** should be **Manim** and/or **Playwright** only.

## Features

**Story pipeline (long-form segments)**

- **TTS narration** — generate MP3 audio from Markdown scripts via OpenAI gpt-4o-mini-tts
- **Manim animations** — primary visual for explaining architecture and flows
- **VHS / `.tape` terminal recordings** — **legacy**; **may be deprecated**. Still supported for existing long-form segments and `kind: cli` manifests; **not** the direction for new docs (use **Manim** + **Playwright**).
- **ffmpeg composition** — combine audio + video into final segments
- **Validation** — OCR error detection, layout analysis, audio-visual sync, narration linting
- **GitHub Pages** — auto-generate `index.html`, deploy workflow, LFS rules, `.gitignore`
- **Wizard** — local web GUI to bootstrap narration scripts from existing project docs

**Playwright-linked tutorials**

- **Per-function videos** — `docgen demo-function`: short clips from **`@playwright/test`** specs, declarative `url`+`actions`, or `discover-tests` / catalog workflows

**No IDE lock-in:** maintenance workflows are **`docgen` CLI + YAML + shell/CI** (and OpenAI where a command calls the API). Editor assistants such as Cursor are **not** required. The wizard is a **local web app**, not a plugin tied to one editor.

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
```

Run the tests:

```bash
pytest                        # unit tests
pytest tests/e2e/ -x          # end-to-end (Playwright, needs `playwright install chromium`)
```

On **Linux**, **legacy VHS** coverage in tests (e.g. `demo_function` `kind: cli`) may need **`ttyd`** and a display (**`xvfb-run -a pytest …`**). CI installs `ttyd`, `xvfb`, and `ffmpeg` via apt (see `.github/workflows/ci.yml`).

**Roadmap:** [milestones/README.md](milestones/README.md) (active checklist; [in-repo dogfood](milestones/next-session-dogfood.md) & [upstream dogfood](milestones/upstream-dogfood.md) — `courseforge/course-builder`; archived notes).

## Quick start

```bash
cd your-project/docs/demos
docgen wizard              # optional: bootstrap narration from project docs
docgen generate-all        # long-form: TTS → Manim (+ optional Playwright segments) → compose → …
docgen demo-function …     # short Playwright tutorial from a test or sidecar YAML
docgen validate --pre-push
```

## CLI commands

| Command | Description |
|---------|-------------|
| `docgen wizard [--port 8501]` | Launch narration setup wizard (local web GUI) |
| `docgen tts [--segment 01] [--dry-run]` | Generate TTS audio |
| `docgen manim [--scene StackDAGScene]` | Render Manim animations |
| `docgen vhs [--tape 02-quickstart.tape] [--strict] [--timeout 120]` | **Legacy** — VHS `.tape` (**may be deprecated**); prefer **Manim** / **Playwright** |
| `docgen playwright --script scripts/capture.py --url http://localhost:3000 --source demo.mp4` | Capture browser demo video with Playwright script |
| `docgen demo-function --manifest <path> --output <dir> [--cache-dir <dir>] [--no-narration]` | **Playwright-centered:** one short tutorial MP4 per function — from a Playwright test/spec, declarative `url`+`actions`, or `*.docgen.yaml` / pytest marker (`--output-dir` is a deprecated alias) |
| `docgen tape-lint [--tape 02-quickstart.tape]` | **Legacy** — lint tapes for VHS |
| `docgen sync-vhs [--segment 01] [--dry-run]` | **Legacy** — rewrite VHS `Sleep` from `animations/timing.json` |
| `docgen compose [01 02 03] [--ffmpeg-timeout 900]` | Compose segments (audio + video) |
| `docgen validate [--max-drift 2.75] [--pre-push]` | Run all validation checks |
| `docgen concat [--config full-demo]` | Concatenate full demo files |
| `docgen pages [--force]` | Generate index.html, pages.yml, .gitattributes, .gitignore |
| `docgen generate-all [--skip-tts] [--skip-manim] [--skip-vhs] [--retry-manim]` | Full pipeline (**`--skip-vhs`** recommended once tapes are retired) |
| `docgen rebuild-after-audio` | Recompose + validate + concat |
| `docgen self catalog-issue-template [--path]` | Print bundled GitHub issue template for catalog CI (works after `pip install docgen`) |
| `docgen catalog init [--force]` | Create ``docgen.catalog.yaml`` at repo root (see `Config.catalog_file_path`) |
| `docgen catalog reset [--yes]` | Replace catalog with an empty entry list (same schema as init); use `-y` / `--yes` for CI |
| `docgen catalog stale [--quiet]` | Exit 1 if any entry needs regen (fingerprints / env overrides / pins), else 0 |
| `docgen catalog refresh [--clear-pins]` | Recompute all ``fingerprints.inputs`` and save the catalog |
| `docgen narration-generate --segment 01 [--extra-path REL] [--hint TEXT] [--dry-run] [--force]` | Generate narration ``.md`` from repo sources + **owner** hints (OpenAI); see ``narration_from_source`` in YAML |
| `docgen yaml-generate [--merge-defaults] [--llm] [--dry-run] [--list-gaps]` | Merge defaults into ``docgen.yaml`` (e.g. archive excludes, skeleton blocks); optional OpenAI refresh of ``tts.instructions`` / ``wizard.system_prompt``; **rewrites file** (comments not preserved — review in Git) |
| `docgen scene-generate --segment 08 [--class-name …] [--extra-path …] [--hint …] [--dry-run] [--print-only]` | Generate or replace one Manim scene class in ``animations/scenes.py`` from narration + ``manim_scene_generation`` config (OpenAI) |
| `docgen discover-tests` | List Node ``@playwright/test`` cases (`--format` yaml, json, catalog). With ``docgen.yaml``, scans ``discover_tests.roots`` (default ``["."]``). ``--repo-root`` limits discovery to one directory (repo root for paths still comes from config). Flags: ``--suggest-visual-map``, ``--write-suggest-visual-map PATH``, ``--playwright-insights``, ``--merge-catalog`` |

**Reusable GitHub Actions:** [`.github/workflows/reusable-docgen-catalog.yml`](.github/workflows/reusable-docgen-catalog.yml) — install docgen from a git ref, `catalog init`, then `catalog stale` and expose `needs_regen` for caller jobs.

## Configuration

Create a `docgen.yaml` in your demos directory. Use **`docgen init`** for a fresh layout, or see [`docs/demos/docgen.yaml`](docs/demos/docgen.yaml) for this repo’s full dogfood bundle (`docgen yaml-generate` keeps defaults and `manim_scene_generation.segments` in step with **`visual_map`**). The **`visual_map`** key is **maintainer-owned** wiring (Manim / VHS / Playwright per segment); optional **`discover-tests --suggest-visual-map`** helps draft **`playwright_test`** entries — see [`docs/demos/README.md`](docs/demos/README.md#visual_map-in-docgenyaml).

### `env_file` and the shell

If `docgen.yaml` sets `env_file` (often `.env`), variables are loaded with **shell-first** semantics: anything **already exported** in the process (including your IDE or CI) is **not** replaced by the file. To make the file win, set **`DOCGEN_ENV_OVERRIDES=1`** so every key from `env_file` overwrites the environment, or **`DOCGEN_ENV_OVERRIDES=OPENAI_API_KEY,OTHER_KEY`** for specific keys only.

When `OPENAI_API_KEY` is present in both the shell and `env_file`, docgen prints a one-line hint to stderr so a silent 401 from the wrong key is easier to diagnose.

**Discovery catalog (stable path):** the on-disk catalog for incremental regeneration defaults to **`docgen.catalog.yaml` at the repository root** (the same root used for `repo_root`: nearest `.git` ancestor, or the `repo_root:` setting in `docgen.yaml`). Commit it in consuming repos so discover/narrate/render steps can skip unchanged sources. Override with `catalog.file` (relative paths are resolved from repo root; absolute paths are allowed).

**When the catalog is referenced:** planned narrate/render commands will call `entry_should_run()` (see `docgen.source_catalog`) per entry — stale fingerprints or explicit overrides mean “run”; otherwise skip. **Updating the catalog** should be an explicit step in the same job after a successful regen (refresh fingerprints, then save), not a side effect of unrelated commands.

**Overrides (per consuming repo):** (1) **CI / dispatch** — set `DOCGEN_CATALOG_FORCE_IDS=id1,id2` so GitHub Actions can force specific entries without editing YAML; map `workflow_dispatch` inputs to that env var. (2) **Repo pin** — on a catalog entry set `policy: { regenerate: true }`; the pipeline regens that entry, then run `docgen catalog refresh --clear-pins` and commit. (3) **Global** — set `DOCGEN_CATALOG_FORCE_ALL=1` so `docgen catalog stale` treats every entry as stale. GitHub Actions remains a good driver; the improvement is **layering** env pins for ad-hoc reruns and **policy** pins for “must regen next main run” without churning the whole catalog.

**Narration from source (owner hints):** under `narration_from_source` in `docgen.yaml`, the **project owner** lists optional `hints` (strings). Those hints are **not** from OpenAI — they steer the model (audience, terminology, what to avoid). OpenAI **generates** the narration `.md` from your repo **context** (`context.paths` / `context.globs`, relative to `repo_root`) plus those hints; the result is what `docgen tts` reads. See `docgen.narrate_from_source`.

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

Useful pipeline options:

```yaml
validation:
  max_freeze_ratio: 0.25   # default; trailing-frame pad vs narration length (compose freeze guard + validate)
  # Optional: cap for type playwright / playwright_test only (otherwise max(max_freeze_ratio, 0.45) applies)
  max_freeze_ratio_playwright: 0.65

manim:
  quality: 1080p30          # supports 480p15, 720p30, 1080p30, 1080p60, 1440p30, 1440p60, 2160p60
  manim_path: ""            # optional explicit binary path (relative to docgen.yaml or absolute)

vhs:
  vhs_path: ""              # optional explicit binary path (relative to docgen.yaml or absolute)
  sync_from_timing: false   # opt-in: allow tape Sleep rewrites from timing.json
  typing_ms_per_char: 55    # typing estimate used by sync-vhs
  max_typing_sec: 3.0       # per block cap for typing estimate
  min_sleep_sec: 0.05       # floor for rewritten Sleep values
  render_timeout_sec: 120   # per-tape timeout for `docgen vhs`

playwright:
  python_path: ""           # optional python executable for capture scripts
  timeout_sec: 120          # capture timeout in seconds
  default_url: ""           # fallback URL when visual_map entry omits url
  default_viewport:         # fallback viewport when visual_map entry omits viewport
    width: 1920
    height: 1080

catalog:
  file: docs/docgen.catalog.yaml   # optional; default is <repo_root>/docgen.catalog.yaml

pipeline:
  sync_vhs_after_timestamps: false  # opt-in: run sync-vhs automatically in generate-all/rebuild-after-audio

compose:
  ffmpeg_timeout_sec: 300   # can also be overridden with: docgen compose --ffmpeg-timeout N
  warn_stale_vhs: true      # warns if terminal/*.tape is newer than terminal/rendered/*.mp4
```

If you edit a `.tape` file, run `docgen vhs` before `docgen compose` so compose does not use stale rendered terminal video.

### Playwright visual source (`type: playwright`)

`visual_map` entries can now use a Playwright capture script:

```yaml
visual_map:
  "04":
    type: playwright
    source: 04-browser-flow.mp4
    script: scripts/demo_capture.py
    url: http://localhost:3300
    viewport:
      width: 1920
      height: 1080
```

During `docgen compose`, docgen runs the capture script first (if `source` does not exist yet),
then muxes the generated MP4 with narration audio.

Manual capture (useful while iterating on scripts). Run from the directory that contains `docgen.yaml`, or pass **`--config`** on the main command first, for example:

```bash
docgen --config docs/demos/docgen.yaml playwright \
  --script scripts/demo_capture.py --url http://localhost:3300 --source 04-browser-flow.mp4
```

**`--source` paths:** a **basename** only (e.g. `04-browser-flow.mp4`) is written under **`terminal/rendered/`**. A **relative path that includes a directory** (e.g. `rendered/foo.mp4`) is resolved under the bundle **`base_dir`** (next to `docgen.yaml`), not automatically under `terminal/rendered/`.

**Playwright + TTS:** narration often runs longer than a short UI capture; compose pads the last video frame. If you hit **FREEZE GUARD**, raise `validation.max_freeze_ratio` or set `validation.max_freeze_ratio_playwright`. For `type: playwright` / `playwright_test`, the effective default ceiling is at least **0.45** unless you set a higher `max_freeze_ratio` or an explicit `max_freeze_ratio_playwright`.

Script contract:
- receives env vars: `DOCGEN_PLAYWRIGHT_OUTPUT`, optional `DOCGEN_PLAYWRIGHT_URL`,
  `DOCGEN_PLAYWRIGHT_WIDTH`, `DOCGEN_PLAYWRIGHT_HEIGHT`, and optional segment metadata
- must write an MP4 to the requested output path
- should use headless Playwright for CI compatibility

### Per-function video docs (`docgen demo-function`)

**Primary intent:** **tutorial / demo videos from Playwright** — preferably the **same UI flows you already test** (`@playwright/test`, YAML that mirrors those steps, or `@pytest.mark.docgen`). That keeps clips aligned with real product behavior.

Do **not** default to **VHS** for any new docs: **`demonstration.kind: cli`** and long-form `.tape` segments share the same **legacy / possible deprecation** path. Prefer **`kind: playwright`** for UI and **Manim** in `generate-all` for non-UI explanation. Keep **`kind: cli`** only while maintaining an existing tape.

`docgen demo-function` renders **one short MP4 per function** (one
scenario). Inputs include a **`*.docgen.yaml` sidecar**, a **Playwright
`*.spec.ts`** (with annotation or sibling YAML), or a **`@pytest.mark.docgen`
Python test** (read statically via `ast` — never imported / `exec`'d).
Outputs land in `--output` as:
`rendered.mp4` (real ISO MP4 with audio), `poster.png`, `fragment.txt`
(`fn-<slug>`), `manifest.json` (snapshot, includes captured action `timeline`),
and `cache-status.txt` (`hit` / `miss`).

```bash
docgen demo-function \
  --manifest examples/lesson_compile.docgen.yaml \
  --output /tmp/out \
  --cache-dir /tmp/docgen-cache
```

**Manifest highlights** — see
[`docs/demo-function.md`](docs/demo-function.md) for the full reference
(manifest schema, action kinds, timeline shape, caching semantics):

- `demonstration.actions[*].say` — narration sentence spoken at the moment
  the action runs. When set, the renderer captures wall-clock timestamps
  during the Playwright recording, sends each `say` through OpenAI
  `gpt-4o-mini-tts`, and **mixes the resulting clips back onto the slowed
  video at their captured times** (with caption burn-in synced to match).
  Omit `say` on an action to fall back to single-clip narration of the
  manifest `intent`.
- `output_budget.playback_speed_factor` (default `1.0`, range `[0.25, 4.0]`)
  — post-capture retiming via ffmpeg `setpts`. `0.5` = half speed (clip
  becomes 2× longer); `2.0` = double speed. Slowdown extends the trim cap
  proportionally so slowed clips are not chopped in half.

**Narration is required by default.** Without `OPENAI_API_KEY`, the renderer
**fails fast with `EXIT_TOOLING_MISSING` (exit 2)** — no silent demos
masquerading as complete artifacts. To explicitly opt into a visual-only
clip, pass `--no-narration`.

**Exit codes:**

| Code | Constant | Meaning |
|------|----------|---------|
| `0` | `EXIT_OK` | success |
| `1` | `EXIT_INVALID` | invalid manifest / render failure / transient TTS network error |
| `2` | `EXIT_TOOLING_MISSING` | missing `ffmpeg` / `playwright` / Chromium / `OPENAI_API_KEY` (or key rejected by OpenAI) |
| `78` | `EXIT_NEUTRAL_SKIP` | placeholder manifest (no `url`) — useful in CI |

See [`examples/lesson_compile.docgen.yaml`](examples/lesson_compile.docgen.yaml)
and [`examples/sample_test.py`](examples/sample_test.py) for both input
shapes; [`tests/e2e/test_demo_function_e2e.py`](tests/e2e/test_demo_function_e2e.py)
is the canonical end-to-end test that drives a real Chromium recording with
per-action narration synced to the captured timeline.

### VHS safety (legacy tapes)

> **Product direction:** **VHS may be deprecated.** Prefer **Manim** and **Playwright** for new videos. This section remains for existing `.tape` workflows.

VHS executes commands in a real shell session. For demos, prefer simulated output with `echo`
instead of invoking real services or model inference in the tape itself.

Example:

```tape
Type "echo '$ python -m myapp run --image sample.png'"
Enter
Sleep 1s
Type "echo '[myapp] Loading model... done (2.1s)'"
Enter
```

Helpful checks:

```bash
docgen tape-lint           # flag risky commands in all tapes
docgen vhs --strict        # fail if VHS output includes shell/runtime errors
```

To auto-align tape pacing with generated narration:

```bash
docgen timestamps
docgen sync-vhs --dry-run
docgen sync-vhs
docgen vhs
docgen compose
```

If `compose` fails with `FREEZE GUARD` after fresh timestamps, retry Manim once automatically:

```bash
docgen generate-all --retry-manim
```
## System dependencies

- **ffmpeg** — composition and probing
- **tesseract-ocr** — OCR validation
- **Manim** — primary long-form visuals (optional: `pip install docgen[manim]`)
- **Playwright / Chromium** — `visual_map` browser capture and **`docgen demo-function`**
- **VHS** — **legacy** terminal recorder (charmbracelet/vhs); **may be deprecated**; avoid for new projects

## Downstream: open a tracking issue in a parent repo

After **`pip install docgen`**, the catalog CI checklist ships **inside the package**. Use the CLI (or pipe straight to `gh`):

```bash
# Print absolute path (pass to gh --body-file)
docgen self catalog-issue-template --path

# Or pipe body to stdin
docgen self catalog-issue-template | gh issue create --repo OWNER/REPO --title "Implement docgen catalog workflow in CI" --body-file -
```

From a **git clone** of this repository you can still run **`./scripts/gh-issue-catalog-workflow.sh owner/repo`** (uses `src/docgen/templates/...`, or falls back to `docgen self catalog-issue-template --path` if the template is not in the tree).

## Milestone spec

See [milestone-doc-generator.md](https://github.com/jmjava/tekton-dag/blob/main/milestones/milestone-doc-generator.md) for the full design document.
