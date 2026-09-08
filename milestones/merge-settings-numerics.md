# Milestone: merge settings must not coerce bool tunables

**Status:** Active  
**PR:** [#142](https://github.com/jmjava/documentation-generator/pull/142)  
**Depends on:** `milestones/wizard-narration-mode.md` (PR #141),
`milestones/merge-settings-str-lists.md` (PR #140),
`milestones/generation-numeric-tunables.md` (PR #117)

## Problem

`Config.from_yaml` already requires YAML numbers for
`narration_from_source.temperature` / `max_context_bytes` (#117) and
string `model` (#107). The merge helpers still did:

```python
temperature = float(root.get("temperature", DEFAULT_TEMPERATURE))
max_bytes = int(root.get("max_context_bytes", DEFAULT_MAX_CONTEXT_BYTES))
model = str(root.get("model") or DEFAULT_MODEL)
```

`bool` is a subclass of `int`: `temperature: true` became **1.0**,
`max_context_bytes: true` became a **1-byte** window, `model: true`
became `"True"`. `system_prompt: true` / `class_name: true` became
`"True"` in the LLM prompt.

Wizard generate-narration and `scene-spec-generate` both go through
these merges.

## Goal

Fail closed on present non-number tunables and non-string model /
system_prompt / class_name. Missing/null still uses defaults.
`temperature: 0` still stays 0.

## Done when

- [x] Bool `temperature` / `max_context_bytes` raise
- [x] Bool `model` / `class_name` raise
- [x] Zero temperature still not replaced by the default
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (794 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- `Config.from_yaml` already gates these types for CLI load
- Whisper prompt-cap `int(... or 0)` in timing enrichment (separate)
