# Milestone: yaml-generate must keep string `visual_map` keys

**Status:** Active  
**PR:** [#138](https://github.com/jmjava/documentation-generator/pull/138)  
**Depends on:** `milestones/story-end-probe.md` (PR #137),
`milestones/yaml-generate-mappings.md` (PR #91),
`milestones/empty-segments-all.md` (PR #124)

## Problem

`Config.from_yaml` already rejects unquoted `visual_map: { 01: … }`
(`visual_map key must be a YAML string`) and unquoted `segments.all: [01]`.

`docgen yaml-generate` (and the wizard focus path) still load a raw mapping
via `load_yaml_mapping` and walk it with `str(seg_id)` / `existing.get(sid,
existing.get(seg_id))`. YAML `01:` is integer `1`, which does **not** match
`segments.all: ["01"]`. Discovery treats the committed manim row as an
empty slot, assigns an unused `*Scene` class, then `vm.clear();
vm.update(new_vm)` **drops** the integer-key row.

Related fail-open:

- `_segment_all_ids` returned `[]` for a present non-list `all`/`default`
  (silent skip). Integer items were kept and `str(1)` missed `"01"`.
- `merge_hint_declared_segments` skipped a non-list `all`, then **created
  empty** `default`/`all` lists, wiping the original value.

## Goal

Fail closed. Do not coerce int `1` to `"01"`.

1. `visual_map` keys must be YAML strings in `discover_visual_map` and
   manim sync (same `require_yaml_string` as config load).
2. `_segment_all_ids`: missing/null still `[]`; present non-list raises;
   items must be strings.
3. `merge_hint_declared_segments`: present non-list `all`/`default` raises
   instead of replacing with empty lists.

## Done when

- [x] Integer `visual_map` key raises; `KeepScene` on key `1` is not rewritten
- [x] Integer `segments.all` item raises; committed `"01"` manim row is kept
- [x] Non-list `segments.all` raises (discover + hint-declared merge)
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (779 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Coercing unquoted `01` to `"01"` (Config already rejects; keep that)
- Hint `docgen.segment.id: 5` → zfill `"05"` (intentional)
- `Config.from_yaml` already gates these types for CLI load; this PR is
  the merge/discover path that still saw raw dicts
