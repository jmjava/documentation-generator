# Milestone: scene-spec layout gaps must be YAML numbers

**Status:** Shipped  
**PR:** [#148](https://github.com/jmjava/documentation-generator/pull/148)  
**Depends on:** `milestones/scene-spec-bool-numerics.md` (PR #147)

## Problem

PR #147 typed `wait_word` / `run_time` / sizes / `page_transition_run_time`.
Layout gaps still go through ``float()`` at compile:

```python
first_row_title_buff = float(layout.get("first_row_title_buff", 0.5))
row_gap = float(layout.get("row_gap", 0.6))
column_gap = float(layout.get("column_gap", 0.8))
```

`bool` is a subclass of `int`: `first_row_title_buff: true` becomes
**1.0** (looks like a valid gap). A string raises at compile, not at
`validate_scene_spec`.

## Goal

Present `layout.first_row_title_buff` / `row_gap` / `column_gap` must
be YAML numbers (not bool). Missing keys keep compile defaults.

## Done when

- [x] Bool / string layout gaps raise `SceneSpecError`
- [x] Missing gaps still validate (defaults at compile)
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (821 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Range floors (`MIN_TITLE_ROW_BUFF`) stay density warnings
- Issue #56
