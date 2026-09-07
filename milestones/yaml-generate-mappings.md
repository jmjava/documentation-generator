# Milestone: yaml-generate must not wipe non-mapping blocks

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/context-path-lists.md` (PR #90),
`milestones/config-mapping-keys.md` (PR #83)

## Problem

`Config.from_yaml` already rejects list/scalar `visual_map`, `narration_from_source`,
`manim_scene_generation`, `manim`, `wizard`, `segments`, and `segment_names`.
Library callers of `merge_defaults` / `merge_hint_wiring` / `discover_visual_map`
(and the wizard focus PUT, which reloads raw YAML then merges) still **replaced**
those values with `{}` when the type was wrong.

A typo or a half-edited in-memory dict silently dropped committed wiring instead
of failing.

## Goal

Fail closed with `ValueError` (CLI `yaml-generate` already maps that to
`ClickException`). Missing keys may still default to `{}`.

## Done when

- [x] Present non-mapping `visual_map` / `narration_from_source` /
      `manim_scene_generation` / `manim` / `wizard` / nested `segments` raise
      instead of being replaced with `{}`.
- [x] `discover_visual_map`, `_sync_manim_scenes_from_visual_map`, and
      `_sync_manim_segments_from_visual_map` raise on a list/scalar `visual_map`
      (including when `discovery.auto_visual_map: false` skips discovery).
- [x] Hint project merge and declared-segment merge do not overwrite a list
      `narration_from_source` / `segments` / `segment_names`.
- [x] Tests for list/string blocks via `merge_defaults`, `merge_hint_wiring`,
      `discover_visual_map`, `merge_hint_project`, `merge_hint_declared_segments`.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- `Config.from_yaml` already gates these types for CLI load; this PR is the
  merge/discover path that still saw raw dicts.
- Empty mappings (`visual_map: {}`) remain allowed.
- `wizard.exclude_patterns` as a non-list still resets to `[]` (list-valued
  default, not a mapping wipe).
