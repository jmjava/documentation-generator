# Milestone: compose must not accept a timed-out ffmpeg mux

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/pipeline-fail-closed.md`,
`milestones/visual-beats-numeric.md` (PR #120)

## Problem

``Composer._run_ffmpeg`` treated ``subprocess.TimeoutExpired`` as
**success** when the output path already existed and had a non-zero
size. A hung mux could leave a truncated ``recordings/<stem>.mp4``;
compose printed a warning, returned, and counted the segment as
composed. Concat already raises ``ConcatError`` on ffmpeg timeout.

## Goal

Fail closed. A timed-out ffmpeg compose run must raise
``ComposeError`` even when a partial output file exists. Remove the
incomplete file so later stages cannot treat it as a finished
recording.

## Done when

- [ ] Timeout with a partial output raises ``ComposeError``.
- [ ] Incomplete output is removed.
- [ ] Tests cover timeout with and without an existing output file.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing ``compose.ffmpeg_timeout_sec`` defaults.
- Duration-probe SKIP when ffprobe is missing (pipeline still fails
  when mapped segments are not composed).
- Manim render timeouts (already treated as a failed scene, not a
  successful mp4).
