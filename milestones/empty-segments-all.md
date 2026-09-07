# Milestone: empty segments.all must not fall through to default

**Status:** Active  
**PR:** [#124](https://github.com/jmjava/documentation-generator/pull/124)  
**Depends on:** `milestones/concat-ffmpeg-timeout.md` (PR #123),
`milestones/yaml-generate-mappings.md` (PR #91)

## Problem

``Config.segments_all`` honors an explicit empty ``segments.all: []``
(no segments). ``yaml-generate`` used ``all or default``, so an empty
list was treated as missing:

1. ``discover_visual_map`` assigned Manim classes to ``default`` ids
   and rewrote ``visual_map``.
2. ``manim.scenes`` sync walked ``default`` instead of empty ``all``.
3. ``--list-gaps`` treated ``default`` ids as already in ``all``.

## Goal

When ``segments.all`` is present (including ``[]``), yaml-generate
must use that list. Fall back to ``segments.default`` only when
``all`` is missing or null — the same rule as ``Config.segments_all``.

## Done when

- [x] Empty ``all: []`` does not discover/sync from ``default``.
- [x] Missing ``all`` still uses ``default``.
- [x] Tests cover segments_in_config, discover_visual_map, and
      manim.scenes sync.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (713 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing how hint ``docgen.segment.create`` appends into existing
  lists.
- Coercing non-list ``all`` values (Config already rejects those).
