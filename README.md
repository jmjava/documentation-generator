# docgen — documentation generator

Reusable Python library and CLI for producing narrated demo videos from Markdown, Manim animations, and VHS terminal recordings.

# Video documentation for this project was generated with the library
https://jmjava.github.io/documentation-generator/

## Features

- **TTS narration** — generate MP3 audio from Markdown scripts via OpenAI gpt-4o-mini-tts
- **Manim animations** — render programmatic animation scenes
- **VHS terminal recordings** — render `.tape` files into MP4s
- **ffmpeg composition** — combine audio + video into final segments
- **Validation** — OCR error detection, layout analysis, audio-visual sync, narration linting
- **GitHub Pages** — auto-generate `index.html`, deploy workflow, LFS rules, `.gitignore`
- **Wizard** — local web GUI to bootstrap narration scripts from existing project docs

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

On **Linux**, VHS-backed tests (e.g. `demo_function` CLI render) need **`ttyd`** and a display (**`xvfb-run -a pytest …`** or a real X session). CI installs `ttyd`, `xvfb`, and `ffmpeg` via apt (see `.github/workflows/ci.yml`).

## Quick start

```bash
cd your-project/docs/demos
docgen wizard            # launch setup wizard to create narration from project docs
docgen generate-all      # run full pipeline: TTS → Manim → VHS → compose → validate → concat → pages
docgen validate --pre-push  # validate all outputs before committing
```

## CLI commands

| Command | Description |
|---------|-------------|
| `docgen wizard [--port 8501]` | Launch narration setup wizard (local web GUI) |
| `docgen tts [--segment 01] [--dry-run]` | Generate TTS audio |
| `docgen manim [--scene StackDAGScene]` | Render Manim animations |
| `docgen vhs [--tape 02-quickstart.tape] [--strict] [--timeout 120]` | Render VHS terminal recordings |
| `docgen playwright --script scripts/capture.py --url http://localhost:3000 --source demo.mp4` | Capture browser demo video with Playwright script |
| `docgen demo-function --manifest <path> --output-dir <dir> [--cache-dir <dir>] [--no-narration]` | Render one short, single-purpose video per function from a declarative manifest |
| `docgen tape-lint [--tape 02-quickstart.tape]` | Lint tapes for commands likely to hang in VHS |
| `docgen sync-vhs [--segment 01] [--dry-run]` | Rewrite VHS `Sleep` values from `animations/timing.json` |
| `docgen compose [01 02 03] [--ffmpeg-timeout 900]` | Compose segments (audio + video) |
| `docgen validate [--max-drift 2.75] [--pre-push]` | Run all validation checks |
| `docgen concat [--config full-demo]` | Concatenate full demo files |
| `docgen pages [--force]` | Generate index.html, pages.yml, .gitattributes, .gitignore |
| `docgen generate-all [--skip-tts] [--skip-manim] [--skip-vhs] [--retry-manim]` | Run full pipeline (optionally auto-retry Manim after FREEZE GUARD) |
| `docgen rebuild-after-audio` | Recompose + validate + concat |
| `docgen self catalog-issue-template [--path]` | Print bundled GitHub issue template for catalog CI (works after `pip install docgen`) |
| `docgen catalog init [--force]` | Create ``docgen.catalog.yaml`` at repo root (see `Config.catalog_file_path`) |
| `docgen catalog stale [--quiet]` | Exit 1 if any entry needs regen (fingerprints / env overrides / pins), else 0 |
| `docgen catalog refresh [--clear-pins]` | Recompute all ``fingerprints.inputs`` and save the catalog |
| `docgen narration-generate --segment 01 [--extra-path REL] [--hint TEXT] [--dry-run] [--force]` | Generate narration ``.md`` from repo sources + **owner** hints (OpenAI); see ``narration_from_source`` in YAML |
| `docgen discover-tests` | List Node ``@playwright/test`` cases (`--format` yaml, json, catalog). With ``docgen.yaml``, scans ``discover_tests.roots`` (default ``["."]``). ``--repo-root`` limits discovery to one directory (repo root for paths still comes from config). Flags: ``--suggest-visual-map``, ``--write-suggest-visual-map PATH``, ``--playwright-insights``, ``--merge-catalog`` |

**Reusable GitHub Actions:** [`.github/workflows/reusable-docgen-catalog.yml`](.github/workflows/reusable-docgen-catalog.yml) — install docgen from a git ref, `catalog init`, then `catalog stale` and expose `needs_regen` for caller jobs.

## Configuration

Create a `docgen.yaml` in your demos directory. See [examples/minimal-bundle/docgen.yaml](examples/minimal-bundle/docgen.yaml) for a starting point.

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

Manual capture (useful while iterating on scripts):

```bash
docgen playwright --script scripts/demo_capture.py --url http://localhost:3300 --source 04-browser-flow.mp4
```

Script contract:
- receives env vars: `DOCGEN_PLAYWRIGHT_OUTPUT`, optional `DOCGEN_PLAYWRIGHT_URL`,
  `DOCGEN_PLAYWRIGHT_WIDTH`, `DOCGEN_PLAYWRIGHT_HEIGHT`, and optional segment metadata
- must write an MP4 to the requested output path
- should use headless Playwright for CI compatibility
### Per-function video docs (`docgen demo-function`)

`docgen demo-function` renders **one short, single-purpose MP4 per function** —
the docs-site analogue of a single Playwright `test('…')` describing one
behavior. Inputs are declarative: either a `*.docgen.yaml` sidecar or a
`@pytest.mark.docgen(...)` decorator on a Python test (read statically via
`ast` — never imported / `exec`'d). Outputs are five files in `--output-dir`:
`rendered.mp4` (real ISO MP4), `poster.png`, `fragment.txt` (`fn-<slug>`),
`manifest.json` (snapshot), and `cache-status.txt` (`hit` / `miss`).

```bash
docgen demo-function \
  --manifest examples/lesson_compile.docgen.yaml \
  --output-dir /tmp/out \
  --cache-dir /tmp/docgen-cache
```

Exit codes: `0` success, `1` invalid manifest / render failure, `2` missing
`ffmpeg` / `playwright`, `78` neutral skip (placeholder manifest with no
`url` — useful in CI). When `OPENAI_API_KEY` is set, the intent line is
narrated via `gpt-4o-mini-tts` and muxed onto the video; pass
`--no-narration` to skip TTS even if the key is set. See
[`examples/lesson_compile.docgen.yaml`](examples/lesson_compile.docgen.yaml)
and [`examples/sample_test.py`](examples/sample_test.py) for both input
shapes.

### VHS safety: avoid real long-running commands in tapes

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
- **VHS** — terminal recording (charmbracelet/vhs)
- **Manim** — animation rendering (optional, install with `pip install docgen[manim]`)

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
