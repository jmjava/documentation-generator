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
| `docgen vhs [--tape 02-quickstart.tape] [--strict]` | Render VHS terminal recordings |
| `docgen sync-vhs [--segment 01] [--dry-run]` | Rewrite VHS `Sleep` values from `animations/timing.json` |
| `docgen compose [01 02 03] [--ffmpeg-timeout 900]` | Compose segments (audio + video) |
| `docgen validate [--max-drift 2.75] [--pre-push]` | Run all validation checks |
| `docgen concat [--config full-demo]` | Concatenate full demo files |
| `docgen pages [--force]` | Generate index.html, pages.yml, .gitattributes, .gitignore |
| `docgen generate-all [--skip-tts] [--skip-manim] [--skip-vhs]` | Run full pipeline |
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

pipeline:
  sync_vhs_after_timestamps: false  # opt-in: run sync-vhs automatically in generate-all/rebuild-after-audio

compose:
  ffmpeg_timeout_sec: 300   # can also be overridden with: docgen compose --ffmpeg-timeout N
  warn_stale_vhs: true      # warns if terminal/*.tape is newer than terminal/rendered/*.mp4
```

If you edit a `.tape` file, run `docgen vhs` before `docgen compose` so compose does not use stale rendered terminal video.

To auto-align tape pacing with generated narration:

```bash
docgen timestamps
docgen sync-vhs --dry-run
docgen sync-vhs
docgen vhs
docgen compose
```
## System dependencies

- **ffmpeg** — composition and probing
- **tesseract-ocr** — OCR validation
- **VHS** — terminal recording (charmbracelet/vhs)
- **Manim** — animation rendering (optional, install with `pip install docgen[manim]`)

## Milestone spec

See [milestone-doc-generator.md](https://github.com/jmjava/tekton-dag/blob/main/milestones/milestone-doc-generator.md) for the full design document.
