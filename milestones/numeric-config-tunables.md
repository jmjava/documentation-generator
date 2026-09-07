# Milestone: pipeline numeric tunables must be YAML numbers

**Status:** Shipped  
**PR:** [#115](https://github.com/jmjava/documentation-generator/pull/115)  
**Depends on:** `milestones/discovery-bool-flags.md` (PR #114),
`milestones/manim-font-quality.md` (PR #106)

## Problem

Config properties wrap tunables in ``int()`` / ``float()``. A YAML
**bool** is a subclass of ``int``, so:

1. ``compose.ffmpeg_timeout_sec: true`` became timeout **1 second**.
2. ``manim.min_font_size: true`` became font size **1**.
3. ``validation.max_freeze_ratio: true`` became **1.0** (allow a fully
   frozen video).

A YAML **list** or **string** raised ``TypeError`` / ``ValueError`` at
timestamps, compose, or validate — not ``ConfigError`` at load.

## Goal

Fail closed at ``Config.from_yaml``. Present values of:

- ``timestamps.silence_noise_db`` / ``min_silence_sec``
- ``manim.min_font_size``
- ``compose.ffmpeg_timeout_sec``
- ``validation.max_drift_sec`` / ``max_freeze_ratio``

must be YAML numbers (int or float, not bool). Missing keys keep
defaults.

## Done when

- [x] Present tunables must be YAML numbers (bool / list / string
      rejected).
- [x] Tests for bool ``ffmpeg_timeout_sec`` / ``min_font_size``, list
      ``silence_noise_db`` / ``max_drift_sec``, and valid numbers.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (669 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Nested validation numerics (``ocr.sample_interval_sec``,
  ``av_sync.tolerance_sec``, ``story_end.max_early_sec``, …).
- LLM ``temperature`` / ``max_context_bytes``.
- Coercing numeric strings (``"300"``) into numbers.
