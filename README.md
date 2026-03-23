# docgen — documentation generator

Reusable Python library and CLI for producing narrated demo videos from Markdown, Manim animations, and VHS terminal recordings.

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
| `docgen compose [01 02 03]` | Compose segments (audio + video) |
| `docgen validate [--max-drift 2.75] [--pre-push]` | Run all validation checks |
| `docgen concat [--config full-demo]` | Concatenate full demo files |
| `docgen pages [--force]` | Generate index.html, pages.yml, .gitattributes, .gitignore |
| `docgen generate-all [--skip-tts] [--skip-manim] [--skip-vhs]` | Run full pipeline |
| `docgen rebuild-after-audio` | Recompose + validate + concat |

## Configuration

Create a `docgen.yaml` in your demos directory. See [examples/minimal-bundle/docgen.yaml](examples/minimal-bundle/docgen.yaml) for a starting point.

## System dependencies

- **ffmpeg** — composition and probing
- **tesseract-ocr** — OCR validation
- **VHS** — terminal recording (charmbracelet/vhs)
- **Manim** — animation rendering (optional, install with `pip install docgen[manim]`)

## Milestone spec

See [milestone-doc-generator.md](https://github.com/jmjava/tekton-dag/blob/main/milestones/milestone-doc-generator.md) for the full design document.
