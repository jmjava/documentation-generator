# Milestone: scene-spec numerics must not coerce bools

**Status:** Active  
**PR:** [#147](https://github.com/jmjava/documentation-generator/pull/147)  
**Depends on:** `milestones/grok-stt-start-end.md` (PR #146),
`milestones/visual-beats-numeric.md` (PR #120)

## Problem

Config generation tunables already reject YAML bools (#117 / #120).
Scene-spec validation still uses ``isinstance(v, (int, float))`` and
``isinstance(ww, int)``. ``bool`` is a subclass of ``int``, so:

1. ``wait_word: true`` became index **1** (pace at the second token).
2. ``run_time: true`` / ``width: true`` became **1**.
3. ``title.font_size: true`` was never type-checked, then ``int(True)``
   compiled font size **1**.
4. ``layout.page_transition_run_time: true`` passed the ``(0, 5]``
   range as **1.0**.

`scene-compile` / `load_scene_spec` both go through `validate_scene_spec`.

## Goal

Present spec numbers must be YAML numbers (int or float, not bool).
Present `wait_word` / `wait_segment` must be YAML ints (not bool).
Missing optional keys keep defaults. Explicit `wait_word: 0` stays 0.

## Done when

- [x] Bool `wait_word` / `run_time` / `width` / `title.font_size` /
      `page_transition_run_time` raise `SceneSpecError`
- [x] `wait_word: 0` still validates
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (818 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- `layout_stack_budget` defaulting a missing title font_size to 36
- Shape / reveal string allowlists (`str(true)` is not in the set)
- Issue #56 (label → `wait_word` semantic drift)
