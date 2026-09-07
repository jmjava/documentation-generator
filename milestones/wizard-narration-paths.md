# Milestone — Wizard narration paths and timing.json

**Goal:** Wizard generate-narration must not call the LLM with empty or
dropped source files, and per-segment timestamps must not wipe
`timing.json` when the file is corrupt.

**Branch / PR:** `cursor/wizard-narration-paths-2ccd`

Follows **[validate-fail-closed.md](validate-fail-closed.md)** (#80).

## Shipped

- [x] `/api/generate-narration` returns 400 when a listed `source_path`
      is missing (same contract as hint-save)
- [x] Generate mode requires at least one source file; revise may omit sources
- [x] `generate_narration_via_llm` generate mode rejects empty `source_texts`
- [x] Wizard timestamps step raises on invalid `timing.json` instead of
      replacing it with `{}` (which dropped other stems)

## Not this milestone

- GET `/api/narration` empty 200 for a new segment (authoring UI)
- Archived Playwright / Embabel / slides
