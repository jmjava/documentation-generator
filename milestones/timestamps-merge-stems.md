# Milestone: CLI timestamps must merge stems, not wipe `timing.json`

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/timestamps-fail-closed.md` (PR #78),
`milestones/timing-json-parse.md` (PR #89)

## Problem

Wizard per-segment timestamps **merges** one stem into `timing.json` via
`load_bundle_timing`. CLI `docgen timestamps` / `extract_all` started from `{}`
and rewrote the whole file, so:

1. Extra stems not in `segments.all` were silently dropped.
2. A corrupt file was overwritten instead of failing like compile/validate/wizard
   freshness (`fix or delete it before timestamps/compile`).

Empty `segments.all` still leaves the file unchanged (#78).

## Goal

Load existing `timing.json` with `load_bundle_timing`, update stems for the
current `segments.all` jobs, preserve other keys. Garbage JSON raises
`TimestampError` and does not rewrite.

## Done when

- [x] `extract_all` merges into `load_bundle_timing()` instead of replacing.
- [x] Corrupt JSON / non-object root fails closed; file unchanged.
- [x] Tests: extra stem preserved; corrupt file not rewritten.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- Empty `segments.all` still leaves `timing.json` unchanged (does not parse).
- Missing audio for a listed segment still errors before write (#78).
