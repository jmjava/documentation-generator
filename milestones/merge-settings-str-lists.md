# Milestone: merge settings must not `str()` hint/path lists

**Status:** Active  
**PR:** [#140](https://github.com/jmjava/documentation-generator/pull/140)  
**Depends on:** `milestones/wait-until-word-start.md` (PR #139),
`milestones/context-path-lists.md` (PR #90)

## Problem

`Config.from_yaml` already requires `narration_from_source` /
`manim_scene_generation` `hints` and `context.paths` / `globs` to be
YAML string lists (#90). The merge helpers still used `_as_str_list`:

```python
return [str(i).strip() for i in x if str(i).strip()]
```

A mutated or library-built raw dict could:

- Turn `paths: [1]` into `"1"` (no real file; silent skip)
- Wrap `hints: "Keep it short."` as a one-item list
- Turn a mapping `context` into `[]` and run the LLM with no focus files

Wizard generate-narration and `scene-spec-generate` both go through these
merges.

## Goal

Fail closed. Do not coerce. Missing/null lists stay `[]`.

## Done when

- [x] Integer / bool hint and path items raise
- [x] A bare string `hints` / `paths` raises (not wrapped)
- [x] A non-mapping `context` raises (not skipped)
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (789 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- `Config.from_yaml` already gates these types for CLI load
- Hint `docgen.segment.id` integer zfill (intentional)
- Model / temperature coercion on `cfg.raw` after load
