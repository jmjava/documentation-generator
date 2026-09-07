# Milestone: leftover AI / timestamps / TTS language keys must be strings

**Status:** Active  
**PR:** [#105](https://github.com/jmjava/documentation-generator/pull/105)  
**Depends on:** `milestones/image-generation-strings.md` (PR #104),
`milestones/tts-empty-audio.md` (PR #99),
`milestones/multi-host-ai-hardening.md`

## Problem

`tts.model` / `image_generation.model` are already strings at config load.
These sibling keys were not:

1. **`ai.provider` / `base_url` / `api_key_env`** — a YAML list was
   `str()`’d (`"['openai']"`) into `normalize_provider`.
2. **`timestamps.engine`** — a list became `"['local']"`, then
   `resolve_engine` raised unknown-engine only when timestamps ran.
3. **`tts.language`** — a list was `str()`’d into xAI TTS/STT
   `language`.

## Goal

Fail closed at `Config.from_yaml`. Missing keys still use defaults
(`ai.provider` openai, `timestamps.engine` local, Grok language `en`).

## Done when

- [x] Present `ai.provider` / `base_url` / `api_key_env` must be
      non-empty YAML strings.
- [x] Present `timestamps.engine` must be a non-empty YAML string.
- [x] Present `tts.language` must be a non-empty YAML string.
- [x] Tests for list values of those keys.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Unknown `timestamps.engine` values still fail at `resolve_engine`.
- `manim.font` / `manim.quality` string typing is separate.
