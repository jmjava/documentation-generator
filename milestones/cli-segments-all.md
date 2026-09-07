# Milestone: CLI --all must use Config.segments_all

**Status:** Active  
**PR:** [#125](https://github.com/jmjava/documentation-generator/pull/125)  
**Depends on:** `milestones/empty-segments-all.md` (PR #124)

## Problem

``narration-generate --all`` and ``scene-spec-generate --all`` read
``raw["segments"]["all"] or []``. Missing ``all`` with a populated
``segments.default`` raised ``segments.all is empty`` even though
``Config.segments_all`` (TTS, timestamps, lint, pipeline) falls back
to ``default``.

An explicit empty ``all: []`` must still fail (same as Config).

## Goal

Both commands use ``cfg.segments_all``. Missing ``all`` uses
``default``. Empty ``all: []`` still errors.

## Done when

- [x] ``--all`` with only ``default`` processes those ids.
- [x] ``--all`` with ``all: []`` still errors even if ``default`` has
      ids.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (717 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing TTS / timestamps empty-all contracts.
- Integer segment ids (already rejected at Config load).
