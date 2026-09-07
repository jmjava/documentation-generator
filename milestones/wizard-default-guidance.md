# Milestone: wizard.default_guidance must be a string

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/wizard-prompt-strings.md` (PR #100),
`milestones/visual-map-sources.md` (PR #112)

## Problem

`wizard.system_prompt` / `llm_model` are already typed at config load.
**`wizard.default_guidance`** was not. `wizard_config` merges the block
over a `""` default; a YAML list became a list in that dict instead of
a string (empty allowed, same as `system_prompt`).

## Goal

Fail closed at `Config.from_yaml`. Missing key still uses `""`.

## Done when

- [x] Present `wizard.default_guidance` must be a YAML string (empty
      allowed).
- [x] Tests for a list value and an empty string.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- The wizard UI does not currently read `default_guidance`; this is a
  config-load type gate so a later consumer of `wizard_config` cannot
  inherit a list.
