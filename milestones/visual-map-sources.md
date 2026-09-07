# Milestone: visual_map mixed sources must be a list of strings

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/visual-map-field-strings.md` (PR #108),
`milestones/pages-config-strings.md` (PR #111)

## Problem

`visual_map.<id>.source` is already a YAML string. Mixed rows use
**`sources:`** instead:

1. A YAML **string** (`sources: clip.mp4`) was iterated as characters
   in `Composer.compose_segments`, looking up one-letter paths.
2. A nested list item was passed to `_resolve_source` and Path-joined.

Missing `sources` remains allowed (empty mixed row).

## Goal

Fail closed at `Config.from_yaml`. Present `visual_map.<id>.sources`
must be a YAML list of non-empty strings.

## Done when

- [x] Present `visual_map.<id>.sources` must be a YAML list of strings.
- [x] Tests for a string value and a nested-list item.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- `wizard.default_guidance` type gating is separate.
- Empty `sources: []` remains allowed.
