# Milestone: validation list keys must not be scalars

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/wizard-exclude-lists.md` (PR #94),
`milestones/config-mapping-keys.md` (PR #83)

## Problem

`Config.ocr_config` / `av_sync_config` / `narration_lint_config` do
`defaults.update(block)`. A YAML **string** for a list-valued key overwrites the
default list. Downstream then iterates characters:

1. **`validation.ocr.error_patterns: command not found`** — OCR matches single
   letters instead of the phrase.
2. **`validation.av_sync.visual_types: manim`** — becomes `m/a/n/i`; `av_sync`
   silently skips real manim segments.
3. **`validation.narration_lint.pre_tts_deny_patterns`** (and post) — lint
   searches each character as a deny pattern.

## Goal

Fail closed at `Config.from_yaml` with `string_list_block` when those keys are
present. Missing keys still use the property defaults.

## Done when

- [x] Present `error_patterns`, `visual_types`, `pre_tts_deny_patterns`, and
      `post_tts_deny_patterns` must be YAML lists of strings.
- [x] Tests for string values of those keys.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- Empty lists remain allowed (no OCR patterns / no av_sync types / no deny
  phrases).
- `validation.*.enabled: false` skips are unchanged.
