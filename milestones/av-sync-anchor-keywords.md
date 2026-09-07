# Milestone: av_sync.anchor_keywords must be a mapping of lists

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/wizard-prompt-strings.md` (PR #100),
`milestones/av-sync-scene-spec.md` (PR #98),
`milestones/validation-list-keys.md` (PR #95)

## Problem

`AVSyncValidator._get_anchors` does
`sync_cfg.get("anchor_keywords", {}).get(seg_id, [])` then
`a["keyword"]` / `a["expected_at"]`.

A YAML **list** or **string** for `anchor_keywords` raised `AttributeError`
(or, after #98, became a soft `av_sync` failure). A per-segment **string**
was iterated as characters. A list of strings was not a mapping of
`keyword` / `expected_at`.

`visual_types` is already a typed list. Nested `anchor_keywords` was not.

## Goal

Fail closed at `Config.from_yaml`. Missing / null still means “auto-detect
anchors”.

## Done when

- [x] Present `anchor_keywords` must be a mapping of segment-id strings to
      lists of mappings with a string `keyword`.
- [x] Tests for list/string shapes and a valid mapping.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- `expected_at` numeric type is not gated (still floats at OCR time).
- Empty mapping / empty per-segment lists remain allowed.
