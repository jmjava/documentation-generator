# Milestone: corrupt `timing.json` must not look like empty words

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/wizard-narration-paths.md` (PR #81)

## Problem

Wizard timestamps already refuse to overwrite a corrupt `timing.json`. Compile
and validate still swallowed `JSONDecodeError` and treated the file as missing
words. Paced compile then failed with a “run timestamps” message; `pace: none`
specs compiled as if there were no timing file.

## Goal

One loader: missing file → `{}`; garbage JSON or a non-object root → error.

## Done when

- [x] `load_bundle_timing` in `timestamps.py`
- [x] scene-compile / `linted_class_block_from_spec` raise `SceneGenerationError`
- [x] validate `timing_sync` / `story_end` / `av_sync` fail with the parse error
- [x] `scene_asset_validate` and wizard timestamps reuse the loader
- [x] Tests: corrupt JSON and list-root, including `pace: none`
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- Empty `segments.all` still leaves `timing.json` unchanged (#78)
- Missing `timing.json` still means empty words (paced compile already fails)
