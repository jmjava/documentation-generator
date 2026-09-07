# Milestone: nested validation numerics must be YAML numbers

**Status:** Shipped  
**PR:** [#118](https://github.com/jmjava/documentation-generator/pull/118)  
**Depends on:** `milestones/generation-numeric-tunables.md` (PR #117),
`milestones/numeric-config-tunables.md` (PR #115)

## Problem

Top-level ``validation.max_drift_sec`` / ``max_freeze_ratio`` are
already typed. Nested check tunables still go through ``int()`` /
``float()``. A YAML **bool** is a subclass of ``int``, so:

1. ``validation.av_sync.tolerance_sec: true`` became **1.0s** OCR
   slack (vs default 3.0).
2. ``validation.ocr.min_confidence: true`` became **1**.
3. ``validation.story_end.max_early_sec: true`` became **1s**.

A YAML list or string raised ``TypeError`` / ``ValueError`` inside
validate, not ``ConfigError`` at load.

## Goal

Fail closed at ``Config.from_yaml``. Present values of:

- ``validation.ocr.sample_interval_sec`` / ``min_confidence``
- ``validation.layout.min_spacing_px`` / ``edge_margin_px``
- ``validation.av_sync.tolerance_sec`` / ``min_anchors_per_segment`` /
  ``max_anchors_per_segment``
- ``validation.timing_sync.max_tail_gap_sec`` / ``max_end_overrun_sec``
- ``validation.story_end.max_early_sec`` / ``max_early_ratio``

must be YAML numbers (int or float, not bool). Missing keys keep
defaults.

## Done when

- [x] Present nested tunables must be YAML numbers.
- [x] Tests for bool ``tolerance_sec`` / ``max_early_sec``, list
      ``min_confidence``, quoted ``max_tail_gap_sec``, and valid
      numbers.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (682 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- ``validation.*.enabled`` / ``layout.check_overlap`` /
  ``prefer_scene_spec_labels`` boolean gates.
- Coercing numeric strings into numbers.
