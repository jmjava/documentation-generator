# Milestone: visual_beats must be YAML numbers (no silent auto-fallback)

**Status:** Active  
**PR:** [#120](https://github.com/jmjava/documentation-generator/pull/120)  
**Depends on:** `milestones/generation-numeric-tunables.md` (PR #117),
`milestones/validation-enable-bools.md` (PR #119)

## Problem

`resolve_pace_segment_indices` turns `visual_beats` / `default_visual_beats`
into an int for the scene-spec prompt schedule. A YAML **bool** is a
subclass of ``int``, and invalid types were caught and **auto-estimated**:

1. ``visual_beats: true`` became **one** visual beat (`int(True) == 1`).
2. A list or string raised ``TypeError`` / ``ValueError``, which the
   helper swallowed and replaced with the 4–12 beat auto schedule.
3. ``pace_segment_indices: [true]`` became ``[1]``; a broken list
   returned ``None`` and also fell through to auto.

The LLM then paced the board against the wrong beat count instead of
failing closed at config load or generate time.

## Goal

Fail closed at ``Config.from_yaml`` and at
``resolve_pace_segment_indices``. Present values of:

- ``manim_scene_generation.default_visual_beats``
- ``manim_scene_generation.segments.<id>.visual_beats``
- ``manim_scene_generation.segments.<id>.pace_segment_indices`` (list of
  numbers)

must be YAML numbers (int or float, not bool). Missing keys still
auto-estimate. A present invalid value must not become the auto
schedule.

## Done when

- [x] Present tunables must be YAML numbers / number lists.
- [x] Tests for bool ``visual_beats``, list ``visual_beats``, bool items
      in ``pace_segment_indices``, invalid resolve fallbacks, and valid
      numbers.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (701 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing the auto-estimate formula when keys are missing / null.
- Coercing numeric strings into numbers.
- Per-segment ``temperature`` keys that generation settings do not
  currently read.
