# Milestone: visual_map type/scene/source and segment_names values must be strings

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/generation-model-strings.md` (PR #107),
`milestones/visual-map-row-types.md` (PR #86),
`milestones/segment-id-strings.md` (PR #87)

## Problem

`visual_map` rows are already mappings and keys are already strings.
These inner / sibling wiring values were not:

1. **`visual_map.<id>.type` / `scene` / `class` / `source`** — a YAML
   list was `str()`’d (`"['manim']"`). Compose and pipeline then
   **skipped** the segment (unknown type / missing class) instead of
   failing at config load. `yaml-generate` treated `"['manim']"` as a
   non-manim leftover and preserved the broken row.
2. **`segment_names` values** — keys are strings; a list stem became
   `"['01-intro']"` and asset lookup used a bogus filename.

Empty `type: ""` remains allowed (unmapped / yaml-generate fill).

## Goal

Fail closed at `Config.from_yaml`. Missing fields stay optional.

## Done when

- [x] Present `visual_map.<id>.type` / `scene` / `class` / `source` must
      be YAML strings (empty allowed).
- [x] Present `segment_names` values must be non-empty YAML strings.
- [x] Tests for list values of those keys.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- `visual_map` mixed `sources:` remains a list of paths.
- `env_file` / `repo_root` / `dirs.*` path strings are separate.
- Per-segment generation `system_prompt` / `class_name` are separate.
