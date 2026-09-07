# Milestone: av_sync must not skip unreadable scene specs

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/layout-check-errors.md` (PR #97),
`milestones/validate-fail-closed.md`

## Problem

`AVSyncValidator._anchors_from_scene_specs` swallowed `load_scene_spec`
errors with `continue`. A corrupt or invalid `*.scene.yaml` then looked
like “no spec anchors”, so `_get_anchors` **fell back to transcript
nouns**. OCR could still pass on unrelated long words while the board
YAML was unreadable.

`story_end` already fails when a spec cannot load. `av_sync` did not.

A crash inside `validate_segment_with_timing` also escaped `_check_av_sync`
as a traceback instead of a failed check.

## Goal

Unreadable scene specs fail `av_sync`. Other unexpected errors in the
validator become `passed=False` (soft on `--pre-push`, same as layout).

## Done when

- [x] `load_scene_spec` failure raises instead of skipping the file.
- [x] `_check_av_sync` maps validator exceptions to a failed check.
- [x] Tests: corrupt YAML fails `_get_anchors` / `_check_av_sync`; valid
      spec still prefers scene-spec labels.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- `av_sync` remains **soft** in `validate --pre-push`.
- Tesseract missing still skips.
- `validation.av_sync.anchor_keywords` nested type gating is separate.
