# Milestone: lint empty narration

**Status:** Shipped  
**PR:** #88  
**Depends on:** `milestones/timestamps-empty-words.md` (PR #85)

## Problem

`docgen tts` and `docgen timestamps` reject narration that is empty after
markdown stripping (heading-only / whitespace). `docgen lint` and validate
`narration_lint` still passed those files because `lint_pre_tts` only scans
for deny-patterns and never required spoken prose.

## Goal

Same contract as TTS: empty spoken text is a lint failure.

## Done when

- [x] `lint_pre_tts` fails when `markdown_to_tts_plain` is empty.
- [x] Tests: empty, whitespace-only, heading-only, CLI `docgen lint`.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- GET `/api/narration` still returns empty 200 for a new segment (authoring UI)
- Wizard PUT of empty text still writes the file (lint/TTS catch it later)
