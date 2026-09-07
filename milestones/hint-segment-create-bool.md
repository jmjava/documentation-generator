# Milestone: hint segment create must be a YAML boolean

**Status:** Active  
**PR:** (this PR)  
**Depends on:** `milestones/numeric-config-tunables.md` (PR #115),
`milestones/hint-front-matter-yaml.md` (PR #102),
`milestones/discovery-bool-flags.md` (PR #114)

## Problem

`yaml-generate` inserts `segments.all` ids from `hints/*.md` when
`docgen.segment.create` is truthy. Identity/`bool()` was not used —
any truthy value counted, so:

1. Quoted **`create: "false"`** still declared the segment (non-empty
   strings are truthy).
2. A YAML **list** `stem` was `str()`'d into `segment_names`.
3. A YAML **list** `id` failed the `\d{2}` check and was **skipped**
   (the hint looked like prose-only).

YAML `create: false` already skipped. Integer `id: 5` still pads to
`"05"` (existing contract).

## Goal

Fail closed in `parse_hint_segment_declaration`. Present `create` must
be a YAML boolean. `stem` must be a YAML string. `id` must be a YAML
string or integer (not bool/list).

## Done when

- [x] `create: "false"` raises instead of inserting a segment.
- [x] List `stem` / `id` raise.
- [x] YAML `create: false` still skips; integer `id: 5` still pads.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Changing the integer `id` zfill recovery (`id: 5` → `"05"`).
- `docgen.wiring` value types beyond existing mapping checks.
