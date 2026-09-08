# Milestone: wizard / LLM narration mode must not silently generate

**Status:** Active  
**Depends on:** `milestones/merge-settings-str-lists.md` (PR #140),
`milestones/wizard-json-object.md` (PR #129)

## Problem

Unknown `mode` values were coerced to `"generate"` in three places:

1. Wizard `POST /api/generate-narration`
2. `generate_narration_via_llm`
3. `generate_narration_markdown` (CLI / library)

A typo (`"revis"`, `"delete"`) still called the LLM and could overwrite
the narration file. The wizard also swallowed any exception from
`narration_topic_label` and sent `topic_label=None` to the model.

Missing / null `mode` still defaults to `"generate"`. `"generate"` with
both current narration and revision notes still auto-promotes to
`"revise"`.

## Goal

Unknown `mode` raises / 400. `narration_topic_label` errors are not
swallowed.

## Done when

- [ ] Wizard unknown `mode` returns 400 and does not call the LLM
- [ ] `generate_narration_via_llm` / `generate_narration_markdown` raise
- [ ] Missing `mode` still defaults to generate
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Auto-revise when generate + current_narration + revision_notes
- Issue #56 (scene-spec label drift)
