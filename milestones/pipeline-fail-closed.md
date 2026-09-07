# Milestone — Pipeline fail-closed

**Goal:** `docgen generate-all` and `yaml-generate` must not report success while
dropping still/recording wiring, skipping missing audio, or ignoring validation
failures. Same CLI in Cloud, local Cursor, and Claude Code.

**Branch / PR:** `cursor/pipeline-fail-closed-2ccd`

## Shipped

- [x] `yaml-generate` discovery preserves non-manim `visual_map` rows; Manim
      classes fill only manim-eligible slots (no positional zip onto stills)
- [x] `manim_scene_generation.segments` upserts `class_name` and keeps per-segment
      hints instead of wholesale replace
- [x] `Pipeline.run` fails when compose produces fewer videos than mapped
      segments (including `--skip-tts` with no mp3s)
- [x] Pipeline validate uses `run_pre_push` before concat/pages
- [x] Pipeline does not overwrite an existing `.github/workflows/pages.yml`
- [x] Wizard Open Bundle loads `env_file`
- [x] Grok-only `XAI_API_KEY` auto-selects `grok` (same as Anthropic-only)
- [x] `validation.narration_lint.block_tts_on_pre_lint` runs in `TTSGenerator`
- [x] CLI commands that need a bundle use `require_config` (Click error, not
      `AttributeError`)
- [x] Segment file lookup prefers `segment_names` stem / `{id}-*` (no `*01*` vs
      `101` substring glob)
- [x] Init bundle README `cd` uses the path relative to repo root
- [x] `--repo acme/app` still clones when a local `acme/` directory exists;
      `docs/demos` stays a missing local path
- [x] Wizard `/api/file` uses `relative_to` (no `startswith` prefix escape)
- [x] Corrupt `.docgen-state.json` does not 500 the wizard

## Not this milestone

- Issue #56 scene-spec beat drift (separate)
- Archived Playwright / Embabel / slides roadmaps
- Anthropic TTS/images (no API)
