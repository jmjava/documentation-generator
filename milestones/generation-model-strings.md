# Milestone: narration / scene-generation model and prompts must be strings

**Status:** Shipped  
**PR:** #107  
**Depends on:** `milestones/manim-font-quality.md` (PR #106),
`milestones/wizard-prompt-strings.md` (PR #100)

## Problem

`wizard.llm_model` / `wizard.system_prompt` and `tts.model` are already
typed at config load. These LLM keys were not:

1. **`narration_from_source.model`** — `str()` turned a YAML list into
   `"['gpt-4o']"` and sent it to the chat API.
2. **`narration_from_source.system_prompt`** — a list became a bracketed
   string used as the narration system prompt.
3. **`manim_scene_generation.model` / `system_prompt` /
   `scene_spec_system_prompt`** — same `str()` coercion into scene-spec
   generation.

## Goal

Fail closed at `Config.from_yaml`. Missing keys still use code defaults
(`gpt-4o` / built-in prompts). Empty `system_prompt` strings remain
allowed (same as `wizard.system_prompt`).

## Done when

- [x] Present `narration_from_source.model` must be a non-empty YAML
      string.
- [x] Present `narration_from_source.system_prompt` must be a YAML
      string (empty allowed).
- [x] Present `manim_scene_generation.model` must be a non-empty YAML
      string.
- [x] Present `manim_scene_generation.system_prompt` /
      `scene_spec_system_prompt` must be YAML strings (empty allowed).
- [x] Tests for list values of those keys.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Per-segment `system_prompt` / `class_name` under those blocks.
- `wizard.default_guidance` type gating is separate.
- `env_file` / `repo_root` / `dirs.*` path strings are separate.
