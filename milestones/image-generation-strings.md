# Milestone: image_generation.model / size / quality must be strings

**Status:** Shipped  
**PR:** #104  
**Depends on:** `milestones/image-empty-bytes.md` (PR #103),
`milestones/tts-empty-audio.md` (PR #99)

## Problem

`tts.model` / `tts.voice` are already non-empty YAML strings at config
load. `image_generation.model` / `size` / `quality` were not.

`image_generation_config` does `defaults.update(block)`. A YAML **list**
for `model:` (bullet list of model names) overwrote the default string.
`generate_images_for_spec` then did `str(icfg.get("model"))`, sending
`"['gpt-image-1']"` to the Images API.

## Goal

Fail closed at `Config.from_yaml`. Missing keys still use the property
defaults (`gpt-image-1`, `1536x1024`, no quality).

## Done when

- [x] Present `image_generation.model` / `size` / `quality` must be
      non-empty YAML strings.
- [x] Tests for list values of those keys.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Empty mapping `image_generation: {}` remains allowed (defaults apply).
- `wizard.default_guidance` type gating is separate.
