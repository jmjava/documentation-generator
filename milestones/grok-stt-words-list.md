# Milestone: Grok STT words must be a JSON array of objects

**Status:** Active  
**PR:** (this PR)  
**Depends on:** `milestones/scene-spec-layout-gaps.md` (PR #148),
`milestones/grok-stt-start-end.md` (PR #146),
`milestones/timing-inner-lists.md` (PR #127)

## Problem

PR #146 typed word `start` / `end`. The container still does:

```python
raw_words = parsed.get("words") or []
for w in raw_words:
    if not isinstance(w, dict):
        continue
```

A string `"hello"` iterates characters (all skipped) and writes
**empty** `words` into `timing.json`. A bool / object `words` either
raises `TypeError` uncaught or skips every row. Non-object items are
dropped, so token indices shift.

`segments` that is not a list currently **synthesizes** a single
segment instead of failing.

## Goal

Present `words` / `segments` must be JSON arrays. Items must be JSON
objects. Missing / null `words` still means no word stream. Empty
`segments: []` still synthesizes from words.

## Done when

- [ ] Non-list `words` / `segments` raise `AIError`
- [ ] Non-object `words[]` / `segments[]` raise `AIError`
- [ ] Missing `words` still maps an empty list
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- OpenAI whisper-1 SDK path
- Requiring `end >= start`
- Issue #56
