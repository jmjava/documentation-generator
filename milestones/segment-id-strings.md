# Milestone: quoted string segment ids

**Status:** Shipped  
**PR:** #87  
**Depends on:** `milestones/visual-map-row-types.md` (PR #86)

## Problem

PyYAML parses unquoted `01` as integer `1`. `segments.all`, `visual_map` keys,
`segment_names` keys, `concat` items, and `pages.segments` keys then silently
mismatch quoted `"01"` used everywhere else (`str(1)` becomes `"1"`, not `"01"`).

`yaml.dump` from Python string keys writes `'01':`, so tool-generated configs
are fine. Hand-authored `visual_map: { 01: { type: manim } }` looks mapped and
is treated as unmapped.

## Goal

Fail closed: those ids must be YAML strings. Tell the author to write `"01"`.

## Done when

- [x] `string_list_block` rejects non-string items (`segments.all`, `manim.scenes`).
- [x] `visual_map`, `segment_names`, and `pages.segments` keys must be strings.
- [x] `concat.<name>` list items must be strings (`ConfigError` + `ConcatError`).
- [x] Tests for unquoted `01` in each of those places.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Zero-padding integer `1` → `"01"` (lossy; `1` and `01` are the same YAML int)
- Changing PyYAML dump style (already quotes `'01'`)
