# Milestone: wizard freshness must not treat corrupt `timing.json` as missing

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/timing-json-parse.md` (PR #89),
`milestones/wizard-narration-paths.md` (PR #81)

## Problem

Compile, validate, scene-asset preflight, and wizard **timestamps write** already
fail closed on garbage `timing.json` (`load_bundle_timing` → `TimestampError`).

The wizard **asset freshness** graph still caught `JSONDecodeError` / a list root
and returned “no timing.json entry — run timestamps”. Maintainers saw a missing
step instead of a corrupt file, and `/api/segments` returned 200.

## Goal

Reuse `load_bundle_timing` in the freshness graph. Missing file stays “no entry”.
Corrupt JSON / non-object root raises; wizard list/assets endpoints return 500
and do not rewrite the file.

## Done when

- [x] `_timing_entry_exists` uses `load_bundle_timing` (no silent `False` on
      garbage JSON).
- [x] `GET /api/segments` and `GET /api/segments/<id>/assets` map
      `TimestampError` to HTTP 500 with the parse message.
- [x] Tests for corrupt JSON and a list root.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Missing `timing.json` still shows timestamps as missing.
- CLI `timestamps extract_all` still rewrites the whole file for `segments.all`
  (recovery path; does not merge extra stems).
- Wizard `.docgen-state.json` corrupt still resets to empty (UI session, not
  pipeline timing).
