# Milestone: validate stream/drift probes must honor ffprobe returncode

**Status:** Active  
**PR:** (this PR)  
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

- [ ] `_check_streams` / `_check_drift` fail when `returncode != 0`
- [ ] Successful probes still parse streams / drift as before
- [ ] Tests for leftover JSON on failure vs a real probe
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Soft-check policy for layout / av_sync / freeze_ratio
- Whisper API `start`/`end` `float(... or 0.0)` in `ai_client`
