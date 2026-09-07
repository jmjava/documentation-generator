# Milestone — Validate and remaining silent skips

**Goal:** `docgen validate` must not pass listed segments that have no
narration or that cannot pace a Manim spec. `docgen manim`,
`image-generate --all`, and narration context collection must not report
success while skipping the work that was requested.

**Branch / PR:** `cursor/validate-fail-closed-2ccd`

Follows **[scene-compile-pace.md](scene-compile-pace.md)** (#79).

## Shipped

- [x] `validate` `narration_lint` fails when a listed segment has no
      narration file (same contract as `docgen lint`)
- [x] `validate` `story_end` fails when a Manim spec has paced labels but
      `timing.json` has no words (run `docgen timestamps`)
- [x] `docgen manim` with an empty `manim.scenes` list uses
      `pipeline_manim_scene_names()`; manim `visual_map` rows without a class
      name are an error
- [x] `docgen image-generate --all` fails when Manim segments exist but
      `animations/specs/` is empty
- [x] Declared `narration_from_source` / extra context paths that do not
      exist raise instead of silently dropping files

## Not this milestone

- Missing recordings stay a pre-push **warning** (WIP bundles without video)
- Archived Playwright / Embabel / slides
