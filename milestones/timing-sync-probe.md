# Milestone: timing_sync must fail when the mp3 duration cannot be probed

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/ffprobe-returncode.md` (PR #135)

## Problem

PR #135 made duration probes honor ffprobe ``returncode`` (``None`` on
failure). ``timing_sync`` still treated ``None`` as a **passed skip**.

When the mp3 and ``timing.json`` both exist, that skip hides stale
timestamps: ``docgen validate`` and ``--pre-push`` (where ``timing_sync``
is a hard check) look green.

Missing audio / LFS pointers / disabled config stay skipped.

## Goal

If audio is present (not an LFS pointer) and a timing block has
``words`` / ``segments`` ends, a failed duration probe is
``timing_sync`` **failed**.

## Done when

- [ ] Probe ``None`` fails ``timing_sync`` (does not skip as passed)
- [ ] Missing audio still skips
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Manim/simple compose SKIP when probes fail (CLI still fails if short)
- ``story_end`` still falls back to transcript end when probe fails
