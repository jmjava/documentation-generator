# Milestone 2 — Slide Deck Generation

**Goal:** Add reveal.js slide deck support as a visual source type alongside Manim and VHS.

## Items

- [ ] **`docgen slides` CLI command** — generate a reveal.js slide deck from a simple YAML/Markdown spec per segment
- [ ] **Slide visual type in `visual_map`** — `type: slides` alongside `manim` and `vhs`, with `source: slides/01-overview/index.html`
- [ ] **Auto-screenshot or headless render** — capture slide transitions as MP4 using Playwright or a headless browser, timed to narration via `timing.json`
- [ ] **Slide templates** — ship 2–3 built-in themes (dark tech, light minimal, branded) selectable in `docgen.yaml`
- [ ] **Hot-reload preview** — `docgen slides --preview` opens a local server with live reload for editing slides
- [ ] **Dogfood** — replace one or more Manim segments in docgen's own demos with a slide deck to validate the workflow
