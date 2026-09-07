# Milestone: LLM generation numeric tunables must be YAML numbers

**Status:** Active  
**PR:** (this PR)  
**Depends on:** `milestones/hint-segment-create-bool.md` (PR #116),
`milestones/numeric-config-tunables.md` (PR #115),
`milestones/generation-model-strings.md` (PR #107)

## Problem

`narration-generate` / `scene-spec-generate` wrap generation tunables
in ``float()`` / ``int()``. A YAML **bool** is a subclass of ``int``,
so:

1. ``narration_from_source.temperature: true`` became temperature
   **1.0**.
2. ``max_context_bytes: true`` became a **1-byte** context window.
3. ``max_whisper_words_in_prompt: true`` became **1** (truncate the
   word stream).

A YAML list or string raised ``TypeError`` / ``ValueError`` at generate
time, not ``ConfigError`` at load.

## Goal

Fail closed at ``Config.from_yaml``. Present values of:

- ``narration_from_source.temperature`` / ``max_context_bytes``
- ``manim_scene_generation.temperature`` / ``max_context_bytes``
- ``max_whisper_segments_in_prompt`` / ``max_whisper_words_in_prompt`` /
  ``max_whisper_segment_text_chars``

must be YAML numbers (int or float, not bool). Missing keys keep
defaults.

## Done when

- [x] Present tunables must be YAML numbers.
- [x] Tests for bool temperature, list ``max_context_bytes``, quoted
      whisper cap, and valid numbers.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Nested validation numerics (``ocr.sample_interval_sec``, …).
- Per-segment ``temperature`` keys that generation settings do not
  currently read.
- Coercing numeric strings into numbers.
