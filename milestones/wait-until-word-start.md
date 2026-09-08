# Milestone: wait_until_word must type Whisper `start`

**Status:** Active  
**PR:** [#139](https://github.com/jmjava/documentation-generator/pull/139)  
**Depends on:** `milestones/yaml-visual-map-keys.md` (PR #138),
`milestones/bootstrap-timing-helpers.md` (PR #130),
`milestones/timing-start-end.md` (PR #134)

## Problem

Loaders now reject non-numeric `timing.json` `start` / `end`. Runtime
`_TimedScene.wait_until_word` still did:

```python
try:
    t = float(words[index].get("start", 0.0))
except (TypeError, ValueError):
    return
```

Missing `start` became `0.0`. A string or null `start` was swallowed.
Either way the wait no-op'd and the next reveal dumped at the current
clock (often t=0) — the same class of bug as issue #66.

`pace_to_beat` used `float(row.get("start", 0.0))` with no type check.
`helper_needs_refresh` treated a `_TimedScene` with `not_past` as current
even when `wait_until_word` still swallowed.

## Goal

Fail closed at the clock. Invalid index remains a no-op. Corrupt `start`
raises `TypeError`. `refresh_bootstrap_helpers` rewrites a swallowing
`_TimedScene`.

## Done when

- [x] `wait_until_word` raises on missing / null / non-numeric / bool `start`
- [x] Invalid word index still no-ops
- [x] `pace_to_beat` uses the same start typing
- [x] Stale `_TimedScene` with `not_past` but swallowing `wait_until_word` refreshes
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (786 passed, 1 skipped)
- [x] `docgen benchmark` (clock/helper change; meets baseline, no bump)

## Out of scope

- Issue #56 (scene-spec label → `wait_word` semantic/LLM drift)
- Changing no-op on out-of-range word index
- `scene_clock_harness` skip logging still uses `.get("start", 0.0)` only
  to classify a skip after a successful wait
