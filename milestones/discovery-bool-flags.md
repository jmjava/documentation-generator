# Milestone: discovery flags must be YAML booleans

**Status:** Active  
**PR:** (this PR)  
**Depends on:** `milestones/wizard-default-guidance.md` (PR #113),
`milestones/yaml-generate-mappings.md` (PR #91)

## Problem

`yaml-generate` treats **`discovery.auto_visual_map: false`** as the
opt-out that keeps a committed `visual_map`, and
**`discovery.merge_hint_segments: false`** as the opt-out that skips
hint-driven segment / wiring merges.

Those checks used identity **`is False`**. YAML integer `0` and the
quoted string `"false"` are not the boolean `False`, so:

1. `auto_visual_map: 0` (or `"false"`) still ran discovery and could
   rewrite `visual_map`.
2. `merge_hint_segments: 0` (or `"false"`) still merged hint segments
   and wiring.

Missing keys stay on (current defaults). YAML `false` / `true` still
work.

## Goal

Fail closed at `Config.from_yaml` and again in `yaml-generate` (hint
merge can inject flags after load). Present values must be YAML
booleans.

## Done when

- [x] Present `discovery.auto_visual_map` / `merge_hint_segments` must
      be YAML booleans.
- [x] `yaml-generate` discovery / hint-merge helpers raise on `0` /
      `"false"` instead of treating them as off or on.
- [x] Tests for integer `0`, quoted `"false"`, and real YAML bools.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Coercing `0` / `"false"` / `"no"` into booleans.
- Other config booleans (`manim.scene_lint`,
  `validation.*.enabled`) still use Python `bool()`.
