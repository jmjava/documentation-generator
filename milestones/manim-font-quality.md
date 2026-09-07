# Milestone: manim.font / quality / manim_path must be strings

**Status:** Shipped  
**PR:** #106  
**Depends on:** `milestones/ai-timestamp-strings.md` (PR #105)

## Problem

`ai.provider` / `tts.model` / `image_generation.quality` are already
strings at config load. These Manim keys were not:

1. **`manim.font`** — `manim_font` did `str(...)`, so a YAML list became
   `"['Liberation Sans']"` and Manim rendered with a bogus font.
2. **`manim.quality`** — a list was `str()`’d in `_quality_args` to
   `"['1080p30']"`, missed the preset map, and **silently fell back** to
   720p30 with a warning.
3. **`manim.manim_path`** — a list became `"['/usr/bin/manim']"` and
   binary lookup failed later instead of at config load.

## Goal

Fail closed at `Config.from_yaml`. Missing keys still use defaults
(`Liberation Sans`, `1080p30`, no `manim_path`).

## Done when

- [x] Present `manim.font` / `manim.quality` / `manim.manim_path` must be
      non-empty YAML strings.
- [x] Tests for list values of those keys.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Unknown `manim.quality` strings still warn and fall back to 720p30.
- `manim.min_font_size` remains an int (`int(...)` already TypeErrors on
  a list).
- `wizard.default_guidance` type gating is separate.
