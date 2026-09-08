# Milestone: Whisper prompt caps must not coerce bools

**Status:** Active  
**PR:** [#144](https://github.com/jmjava/documentation-generator/pull/144)  
**Depends on:** `milestones/pages-ffprobe-returncode.md` (PR #143),
`milestones/merge-settings-numerics.md` (PR #142),
`milestones/generation-zero-values.md` (PR #122),
`milestones/generation-numeric-tunables.md` (PR #117)

## Problem

`Config.from_yaml` already requires YAML numbers for
`max_whisper_segments_in_prompt` / `max_whisper_words_in_prompt` /
`max_whisper_segment_text_chars` (#117). Timing enrichment already
type-checks **chars** (#122). The two count caps still do:

```python
max_seg = int(root.get("max_whisper_segments_in_prompt", 0) or 0)
max_words = int(root.get("max_whisper_words_in_prompt", 0) or 0)
```

`bool` is a subclass of `int`: `max_whisper_words_in_prompt: true`
becomes **1** and truncates the word stream the LLM uses for
`wait_word`. A quoted `"12"` becomes 12 instead of raising.

#142 called this out as out of scope of merge-settings numerics.

## Goal

Fail closed on present non-number caps. Missing/null still means 0
(send the full stream). Explicit `0` still means all tokens.

## Done when

- [x] Bool / string whisper count caps raise `SceneGenerationError`
- [x] `max_whisper_words_in_prompt: 0` still lists every word
- [x] Chars type-check stays (shared helper)
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (804 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- `Config.from_yaml` already gates these keys for CLI load
- Validate `_check_streams` / `_check_drift` ffprobe `returncode`
- Whisper API `start`/`end` `float(... or 0.0)` in `ai_client`
