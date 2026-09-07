# Milestone: wizard.system_prompt and llm_model must be strings

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/tts-empty-audio.md` (PR #99),
`milestones/wizard-exclude-lists.md` (PR #94)

## Problem

`wizard.exclude_patterns` / `scan_extensions` are already YAML lists at
config load. `wizard.system_prompt` and `wizard.llm_model` were not.

A bullet-list `system_prompt` overwrote the default string in
`wizard_config` (`defaults.update(block)`). Generate-narration then
passed a list into `chat_completion` (`"str" + list` in revise mode, or
a non-string `content` field). A list `llm_model` was passed as the
OpenAI/Grok model name.

## Goal

Fail closed at `Config.from_yaml`. Missing keys still use
`wizard_config` defaults.

## Done when

- [x] Present `wizard.system_prompt` must be a YAML string (empty allowed).
- [x] Present `wizard.llm_model` must be a non-empty YAML string.
- [x] Tests for list values of those keys.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- Empty `wizard.system_prompt: ""` remains allowed (explicit blank).
- `wizard.default_guidance` type gating is separate.
