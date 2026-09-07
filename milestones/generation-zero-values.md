# Milestone: honor explicit generation zeros (temperature / max_chars)

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/generation-numeric-tunables.md` (PR #117),
`milestones/compose-ffmpeg-timeout.md` (PR #121)

## Problem

Python ``or`` treats ``0`` / ``0.0`` as missing:

1. ``scene-spec-generate`` used
   ``settings.temperature or 0.35``. YAML
   ``manim_scene_generation.temperature: 0`` (deterministic) became
   **0.35**.
2. Timing prompt enrichment used
   ``int(max_whisper_segment_text_chars or 200)``. YAML ``0`` (no
   truncation; same convention as the whisper count caps) became
   **200**. Invalid types were swallowed into 200 instead of failing.

Narration-generate already passes ``settings.temperature`` through, so
``0`` worked there.

## Goal

Honor explicit zeros. Missing / null keys keep defaults (temperature
from merged scene-generation settings; max_chars 200). Present invalid
``max_whisper_segment_text_chars`` raises ``SceneGenerationError``.

## Done when

- [ ] ``temperature: 0`` is sent to the LLM as ``0.0``.
- [ ] ``max_whisper_segment_text_chars: 0`` does not truncate prompt text.
- [ ] Tests cover both zeros and a bool max_chars raise.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Retry jitter (``temperature + 0.15 * attempt`` after a sparse spec).
- Changing default temperatures (merged settings still default to 0.4).
