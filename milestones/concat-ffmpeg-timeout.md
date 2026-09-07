# Milestone: concat must not leave a truncated ffmpeg output

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/compose-ffmpeg-timeout.md` (PR #121),
`milestones/generation-zero-values.md` (PR #122)

## Problem

Compose now raises and unlinks a partial mux on ffmpeg timeout (#121).
Concat already raised ``ConcatError`` on timeout / non-zero ffmpeg, but
it left ``recordings/<target>.mp4`` in place. ``ffmpeg -y`` writes as
it goes, so a hung or failed concat could leave a truncated full-demo
file that ``pages`` / validate treat as a finished recording.

## Goal

On concat ffmpeg timeout, ``CalledProcessError``, or missing ffmpeg,
unlink the incomplete output (same contract as compose). Keep raising
``ConcatError``. Empty concat maps stay a no-op.

## Done when

- [ ] Timeout / failed concat removes the incomplete target mp4.
- [ ] Tests cover timeout and CalledProcessError with a pre-existing
      partial file.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing the 300s concat ffmpeg timeout.
- Empty ``concat:`` maps (still a no-op).
