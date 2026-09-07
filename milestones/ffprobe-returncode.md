# Milestone: ffprobe duration probes must honor returncode

**Status:** Active  
**PR:** [#135](https://github.com/jmjava/documentation-generator/pull/135)  
**Depends on:** `milestones/compose-ffmpeg-timeout.md` (PR #121),
`milestones/timing-start-end.md` (PR #134)

## Problem

Duration probes in compose / TTS / validate / local timestamps ran ffprobe
without checking ``returncode``, then ``float(stdout)``. A failed probe
that still printed a number (or leftover stdout) looked like a real
duration.

``_compose_image`` treated a missing duration as ``-t ""`` and stripped
it, so a looping still was muxed **without** a finite ``-t``.

Manim/simple compose already SKIPs when both probes fail (CLI / pipeline
still fail if composed < mapped). That SKIP stays.

## Goal

``returncode != 0`` is a failed probe (``None``, or ``AlignmentError``
for local timestamps). Image compose raises ``ComposeError`` instead of
dropping ``-t``.

## Done when

- [ ] Compose / TTS / validate probes ignore stdout when ffprobe fails
- [ ] Image compose does not run ffmpeg without a duration
- [ ] Local ``probe_duration`` raises on nonzero ffprobe
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Manim/simple compose SKIP when probes fail (CLI still fails if short)
- Validate ``timing_sync`` still skips as passed when duration is unknown
