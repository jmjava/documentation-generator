# Milestone: Grok STT start/end must be JSON numbers

**Status:** Active  
**PR:** (this PR)  
**Depends on:** `milestones/validate-stream-probe.md` (PR #145),
`milestones/timing-start-end.md` (PR #134),
`milestones/tts-empty-audio.md`

## Problem

`load_bundle_timing` / Manim loaders already require JSON-number `start` /
`end` (#134). Grok STT ingest still does:

```python
"start": float(w.get("start") or 0.0),
"end": float(w.get("end") or 0.0),
```

`bool` is a subclass of `int`: `start: true` becomes **1.0**. Missing /
null `start` waits at **0.0** and dumps the board. `duration: true`
becomes **1.0** for the no-words segment fallback.

That corrupt payload is what `docgen timestamps --engine whisper`
writes into `timing.json` when `ai.provider` is grok.

## Goal

Present word / segment `start` / `end` and present `duration` must be
JSON numbers (not bool). Missing `duration` still falls back to the last
word end. Explicit `start: 0` / `duration: 0` stay 0.

## Done when

- [ ] Bool / missing / string word `start` raises `AIError`
- [ ] `start: 0.0` still maps to `0.0`
- [ ] Present `duration: true` raises `AIError`
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- OpenAI whisper-1 SDK path (typed `.start` / `.end` attributes)
- Requiring `end >= start`
- `words` / `segments` list typing beyond skipping non-object rows
