# Milestone: env_file / repo_root / dirs paths must be strings

**Status:** Shipped  
**PR:** #109  
**Depends on:** `milestones/visual-map-field-strings.md` (PR #108)

## Problem

`manim.manim_path` is already a string at config load. These path keys
were not:

1. **`env_file` / `repo_root`** — a YAML list loaded successfully, then
   `Path / list` TypeError’d when CLI applied the env file or the wizard
   resolved `repo_root`.
2. **`dirs.narration` / `audio` / `animations` / `recordings` / `hints`**
   — a list TypeError’d during `Config.__post_init__` Path joins instead
   of raising `ConfigError`.

## Goal

Fail closed at `Config.from_yaml` with `ConfigError`. Missing keys still
use defaults (`narration/`, git-discovered repo root, no `env_file`).

## Done when

- [x] Present `env_file` / `repo_root` must be non-empty YAML strings.
- [x] Present `dirs.narration` / `audio` / `animations` / `recordings` /
      `hints` must be non-empty YAML strings.
- [x] Tests for list values of those keys.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- `wizard.default_guidance` type gating is separate.
- Per-segment generation `system_prompt` / `class_name` are separate.
- `pages` output directory keys are separate.
