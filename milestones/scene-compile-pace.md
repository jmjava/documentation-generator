# Milestone — Scene compile pacing and visual_map stability

**Goal:** `scene-compile` must not emit unpaced cascading `FadeIn`s when
`timing.json` has no words, and `yaml-generate` must not retarget committed
Manim `visual_map` rows. Related CLI paths (`lint`, `compose`, TTS,
`generate-all`) fail closed instead of exiting 0 on empty work.

**Branch / PR:** `cursor/scene-compile-pace-2ccd`

Follows **[timestamps-fail-closed.md](timestamps-fail-closed.md)** (#78).
Closes the remaining hole in issue #56 (missing/empty Whisper words).

## Shipped

- [x] `pacing_violations` requires `timing.json` words whenever any labeled
      story box is not `pace: none` (unlabeled images stay exempt)
- [x] `linted_class_block_from_spec` / `scene-compile` raise
      `SceneGenerationError` for paced labels when words are missing or empty
- [x] Explicit `pace: none` on every story box still compiles without words
- [x] `discover_visual_map` preserves existing manim `scene` / `class` (even
      when the class is missing from `scenes.py` or the file is empty)
- [x] Unused scene classes fill **empty** manim slots in file order (no
      positional overwrite of a committed class)
- [x] `docgen lint` exits 1 when a listed segment has no narration file
- [x] `docgen compose` with no args uses `segments.default` if nonempty, else
      `segments.all` (empty default no longer composes nothing and succeeds)
- [x] TTS raises `TTSError` when stripped narration is empty
- [x] `generate-all` / `rebuild-after-audio` wrap `RuntimeError` as
      `ClickException` without swallowing `SystemExit` from `run_pre_push`;
      empty `segments.all` is an error

## Not this milestone

- Clock / `_TimedScene` / dwell math (no `docgen benchmark` baseline bump)
- Archived Playwright / Embabel / slides
