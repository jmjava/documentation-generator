# Milestone: image-generate must not write empty assets

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/hint-front-matter-yaml.md` (PR #102),
`milestones/tts-empty-audio.md` (PR #99)

## Problem

`generate_images_for_spec` wrote whatever `image_fn` / the Images API
returned, including **0-byte** files, and reported `generated`. Pipeline
Manim then loaded an empty PNG. TTS already fails closed on empty audio
(#99); images did not.

`generate_image_bytes` also returned empty `b64_json` / URL bodies.

## Goal

Empty provider bytes raise `ImageGenerationError` **before** writing.
`--force` must not clobber a committed asset with empty bytes.

## Done when

- [x] Empty `image_fn` / API bytes raise and do not write a new file.
- [x] `--force` with empty bytes leaves an existing asset unchanged.
- [x] Empty b64 / URL download raises in `generate_image_bytes`.
- [x] Tests for the spec write path.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- `image_generation.model` / `size` string typing is separate.
- Existing non-empty assets are still skipped unless `--force`.
