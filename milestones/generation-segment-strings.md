# Milestone: per-segment generation prompts must be strings

**Status:** Active  
**PR:** [#110](https://github.com/jmjava/documentation-generator/pull/110)  
**Depends on:** `milestones/generation-model-strings.md` (PR #107),
`milestones/path-config-strings.md` (PR #109)

## Problem

Root `narration_from_source.system_prompt` / `manim_scene_generation.model`
are already typed at config load. Per-segment keys were not:

1. **`narration_from_source.segments.<id>.system_prompt` / `topic`** —
   `str()` turned a YAML list into a bracketed string used as the
   narration system prompt or topic line.
2. **`manim_scene_generation.segments.<id>.class_name` /
   `system_prompt` / `scene_spec_system_prompt`** — same coercion into
   the Manim class name or scene-spec system prompt.

Empty `system_prompt` strings remain allowed (same as the root keys).

## Goal

Fail closed at `Config.from_yaml` while walking those segment maps.

## Done when

- [x] Present per-segment `system_prompt` / `topic` /
      `scene_spec_system_prompt` must be YAML strings (empty allowed).
- [x] Present per-segment `class_name` must be a non-empty YAML string.
- [x] Tests for list values of those keys.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- `wizard.default_guidance` type gating is separate.
- `pages.docs_dir` / `title` path and copy strings are separate.
