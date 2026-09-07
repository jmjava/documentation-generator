# Milestone: context path lists and `pages.segments` mapping

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/config-mapping-keys.md` (PR #83),
`milestones/segment-id-strings.md` (PR #87)

## Problem

1. **`pages.segments` as a list** — `_resolve_segments_cfg` only used the block
   when it was a non-empty mapping. A list fell through to discovery and
   silently ignored maintainer titles.
2. **`narration_from_source.context.paths` as a string** — `_as_str_list`
   wrapped a single string as one path (OK) but a mapping or other type
   became `[]`, so narration-generate ran with no focus files.
3. **`manim_scene_generation` as a list** — was not in the Config mapping-key
   gate; later code treated it as `{}`.

## Goal

Fail closed at `Config.from_yaml` for those nested types.

## Done when

- [x] `pages.segments` if present must be a mapping (keys still quoted strings).
- [x] `narration_from_source` / `manim_scene_generation` `hints`,
      `context.paths`, `context.globs` must be string lists; `segments` a mapping
      of mappings.
- [x] Tests for list `pages.segments`, string `context.paths`, list
      `narration_from_source.segments`, string per-segment row, list
      `manim_scene_generation`.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- `_as_str_list` still wraps a single string as a one-item list for library
  callers that do not go through `Config.from_yaml`
- Empty `pages.segments: {}` still falls back to discovery
