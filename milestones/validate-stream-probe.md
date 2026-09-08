# Milestone: validate stream/drift probes must honor ffprobe returncode

**Status:** Shipped  
**PR:** [#145](https://github.com/jmjava/documentation-generator/pull/145)  
**Depends on:** `milestones/whisper-prompt-caps.md` (PR #144),
`milestones/pages-ffprobe-returncode.md` (PR #143),
`milestones/ffprobe-returncode.md` (PR #135)

## Problem

PR #135 made duration probes ignore stdout when ffprobe exits non-zero.
Pages followed in #143. Validate **`_check_streams` / `_check_drift`**
still `json.loads(out.stdout)` with no `returncode` check.

Empty stdout already fails `json.loads` (failed check). Leftover JSON
that lists video+audio streams can **pass** `stream_presence` /
`av_drift` on a corrupt recording. Those checks are hard in
`validate --pre-push` (not in the soft set).

## Goal

Nonzero ffprobe is a failed check. Do not trust leftover JSON.

## Done when

- [x] `_check_streams` / `_check_drift` fail when `returncode != 0`
- [x] Successful probes still parse streams / drift as before
- [x] Tests for leftover JSON on failure vs a real probe
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (808 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Soft-check policy for layout / av_sync / freeze_ratio
- Whisper API `start`/`end` `float(... or 0.0)` in `ai_client`
