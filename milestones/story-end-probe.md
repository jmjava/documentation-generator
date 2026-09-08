# Milestone: story_end must fail when the mp3 duration cannot be probed

**Status:** Shipped  
**PR:** [#137](https://github.com/jmjava/documentation-generator/pull/137)  
**Depends on:** `milestones/timing-sync-probe.md` (PR #136)

## Problem

PR #136 made ``timing_sync`` fail when ffprobe cannot measure the mp3.
``story_end`` still **fell back to transcript end** on a failed probe.

That hides the case the check exists for: last paced reveal near the
last Whisper word while the **audio** keeps going. ``docgen validate``
and ``--pre-push`` (hard ``story_end``) looked green.

Missing audio / LFS pointers still use transcript end, and skip when
that is also missing.

## Goal

If a local mp3 is present (not an LFS pointer), ``story_end`` must probe
it. Probe ``None`` / non-positive duration is a **failed** check.

## Done when

- [x] Probe ``None`` fails ``story_end`` (does not fall back to transcript)
- [x] Missing audio still uses transcript end / skip
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (772 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Manim/simple compose SKIP when probes fail (CLI still fails if short)
- ``timing_sync`` (shipped in #136)
