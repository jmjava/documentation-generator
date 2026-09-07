# Milestone — Manim lint, config YAML, TTS empty-all

**Goal:** `docgen validate` must not pass a Manim segment when
`animations/scenes.py` is missing. Invalid or non-mapping `docgen.yaml` must
not traceback or get rewritten as `{}`. `docgen tts` must not exit 0 when
`segments.all` is empty.

**Branch / PR:** `cursor/manim-lint-config-2ccd`

Follows **[wizard-narration-paths.md](wizard-narration-paths.md)** (#81).

## Shipped

- [x] `validate` `manim_scene_lint` fails when `animations/scenes.py` is
      missing (this check only runs for manim `visual_map` rows)
- [x] `Config.from_yaml` rejects invalid YAML and a non-mapping root
      (`ConfigError`); CLI maps that to `ClickException`
- [x] `yaml-generate` uses the same loader (no traceback, no `or {}` wipe)
- [x] Wizard hint-save yaml-generate does not replace a non-mapping
      `docgen.yaml` with `{}`
- [x] `docgen tts` with empty `segments.all` (no `--segment`) raises
      `TTSError`
- [x] `scene_asset_validate` reports corrupt / non-object `timing.json`
      instead of skipping word checks

## Not this milestone

- Missing recordings stay a pre-push **warning** (WIP bundles)
- `timestamps` with empty `segments.all` still leaves `timing.json`
      unchanged (#78)
- GET `/api/narration` empty 200 for a new segment (authoring UI)
- Archived Playwright / Embabel / slides
