# Milestone — Timestamps, concat, and remaining silent success

**Goal:** Timing, concat, Manim, compose CLI, and wizard steps must not
report success while dropping stems, muxing a partial concat, or ignoring
`ai.base_url` for Anthropic.

**Branch / PR:** `cursor/timestamps-fail-closed-2ccd`

Follows **[pipeline-fail-closed.md](pipeline-fail-closed.md)** (#77).

## Shipped

- [x] Anthropic chat posts to `{ai.base_url or DOCGEN_AI_BASE_URL}/v1/messages`
- [x] `timestamps extract_all` walks `segments.all` via `find_segment_asset`
      (no `*.mp3` glob wipe); missing audio for a listed segment is an error
- [x] `concat` raises on unknown target, missing recordings, or ffmpeg failure
- [x] `ManimRunner.render` raises when `scenes.py` or the manim binary is missing
- [x] `docgen compose` exits non-zero when composed count is short
- [x] Wizard `/api/generate-narration` rejects paths that escape `repo_root`
- [x] Wizard manim / compose / validate steps fail closed

## Not this milestone

- Issue #56 residual (unpaced compile when timing words are missing) —
  see **[scene-compile-pace.md](scene-compile-pace.md)** (#79). Validate
  `story_end` skip for missing words is **[validate-fail-closed.md](validate-fail-closed.md)**.
- Archived Playwright / Embabel / slides
