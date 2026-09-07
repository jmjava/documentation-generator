# Milestone: TTS must not succeed with empty audio or list-valued strings

**Status:** Shipped  
**PR:** #99  
**Depends on:** `milestones/av-sync-scene-spec.md` (PR #98),
`milestones/manim-lint-config.md` (PR #82)

## Problem

1. `TTSGenerator` printed **Wrote** after `synthesize_speech` even when the
   provider wrote a **0-byte** mp3 (or no file). Downstream timestamps then
   ran against empty audio. Chat already fails closed on empty text; TTS did
   not.
2. xAI `_grok_tts` wrote whatever bytes came back, including empty.
3. `tts.model` / `tts.voice` / `tts.instructions` as a YAML **list** loaded
   and were passed to the API (`instructions:` as a bullet list is a common
   typo). `tts.instructions` is typed `str`.

## Goal

Fail closed at config load for non-string TTS fields. Fail closed after
synthesize if the mp3 is missing or empty (unlink the empty file). Grok TTS
raises on an empty HTTP body.

## Done when

- [x] Present `tts.model` / `tts.voice` must be non-empty YAML strings.
- [x] Present `tts.instructions` must be a YAML string (empty string allowed).
- [x] `TTSGenerator` raises `TTSError` and removes a 0-byte output file.
- [x] xAI TTS raises `AIError` on an empty body (does not write the file).
- [x] Tests for list-valued fields, empty provider output, empty Grok body.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Wizard PUT of empty narration still writes the file (lint/TTS catch later).
- `wizard.system_prompt` / `llm_model` type gating is separate.
- Missing `tts` keys still use the built-in defaults.
