# docgen — documentation generator

Reusable Python library and CLI for producing narrated demo videos from Markdown, Manim animations, and VHS terminal recordings.

# Video documentation for this project was generated with the libary
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
| `docgen tape-lint [--tape 02-quickstart.tape]` | Lint tapes for commands likely to hang in VHS |
| `docgen sync-vhs [--segment 01] [--dry-run]` | Rewrite VHS `Sleep` values from `animations/timing.json` |
| `docgen compose [01 02 03] [--ffmpeg-timeout 900]` | Compose segments (audio + video) |
| `docgen validate [--max-drift 2.75] [--pre-push]` | Run all validation checks |
| `docgen concat [--config full-demo]` | Concatenate full demo files |
| `docgen pages [--force]` | Generate index.html, pages.yml, .gitattributes, .gitignore |
| `docgen generate-all [--skip-tts] [--skip-manim] [--skip-vhs] [--retry-manim]` | Run full pipeline (optionally auto-retry Manim after FREEZE GUARD) |
| `docgen rebuild-after-audio` | Recompose + validate + concat |

## Configuration

Create a `docgen.yaml` in your demos directory. See [examples/minimal-bundle/docgen.yaml](examples/minimal-bundle/docgen.yaml) for a starting point.

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

## Milestone spec

See [milestone-doc-generator.md](https://github.com/jmjava/tekton-dag/blob/main/milestones/milestone-doc-generator.md) for the full design document.
