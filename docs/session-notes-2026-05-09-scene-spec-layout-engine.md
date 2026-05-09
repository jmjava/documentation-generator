# Session notes — Scene-spec layout engine + segment 05 (May 9, 2026)

Canonical docs for day-to-day use: **`README.md`** (CLI table), **`AGENTS.md`** (agent context), **`docs/demos/README.md`** (dogfood). This file is a **change log / narrative** for one shipping slice — picks up where [`session-notes-2026-05-08-manim-declarative-specs.md`](session-notes-2026-05-08-manim-declarative-specs.md) left off.

## Problem

Building **segment 05** (`05-playwright-demos`, the long-form explainer for the demo-video pipeline itself) surfaced two recurring failure modes in the declarative scene path that we had been **patching by hand-editing the generated YAML**:

1. **Boxes appearing too early.** Specs used `wait_segment: N` (Whisper segment **start**), but a label often appears mid-segment, so all boxes lit up well before they were spoken. Manual `wait_segment` tweaks per row were a permanent recurring tax.
2. **Boxes scrolling off the screen.** With ~8 rows of labeled boxes for the segment, single-page stacks exceeded the **14.22 × 8** Manim frame budget. Cursor had been hand-restructuring `pages:` and per-row sizes — exactly the “category C” edits the **`no-asset-edits.mdc`** rule forbids.

Plus a smaller third one: the LLM occasionally picked an inflected label (`Tracing`) while the box product name we wanted on screen was the bare stem (`Trace`), and there was no clean way to cite the spoken inflection without hand-editing.

## Solution (shipped) — engine, not asset edits

All fixes live in **`src/docgen/scene_spec.py`** + **`src/docgen/scene_spec_generate.py`**. Generated YAML stays a pure **intent** input.

1. **`wait_at` (absolute seconds)** — alternative to `wait_segment`. The compiler emits `self.wait_until(<seconds>)` directly, so a row appears at the exact moment the spoken word lands rather than at a Whisper segment boundary.
2. **Layout budget primitives** — `FRAME_WIDTH`, `FRAME_HEIGHT`, `_LAYOUT_HORIZONTAL_SAFE`, `_LAYOUT_BOTTOM_MARGIN`, plus `_title_band_estimate(font_size)` and **`layout_stack_budget(title, layout)`**. They derive the **maximum total stack height** that fits below the title given the current `first_row_title_buff`, so the rest of the engine has a single source of truth for “what fits.”
3. **`auto_paginate(spec)`** — accepts a flat `rows:` (intent) **or** an explicit `pages:` (override) and re-paginates greedily to fit `layout_stack_budget`. Existing `pages:` carving and per-page `transition` are preserved for the first chunk; spillover chunks fade in with the spec’s default transition. Specs that already fit are returned unchanged so trivial single-page YAML stays trivial.
4. **`align_wait_at_to_words(spec, words)`** — looks up each row’s **first box label** in the Whisper word list (`timing.json` `words[]`) and snaps its `wait_at` to that word’s `start`. A cursor advances past the matched word so two rows can’t collide on the same occurrence; multi-token labels (`Demo Function`) match a consecutive run.
5. **Stem / inflection matching** — `_stem(token)` strips a small set of English suffixes (`ing`, `tion`, `tions`, `ies`, `edly`, `ed`, `ly`, `es`, `s`, `e`) so `Trace` aligns to spoken `tracing`, `Compose` to `composing`, etc. Tokens shorter than 4 chars (e.g. `TTS`) keep strict equality so short product names don’t snag random words.
6. **`layout_budget_violations(spec)`** — `scene-spec-generate` rejects LLM output that exceeds the vertical stack budget or the safe horizontal width and writes the offending YAML to a `*.draft.yaml` for inspection. `scene-compile` does **not** enforce this (hand-curated specs may intentionally push limits).

`scene_spec_generate.linted_class_block_from_spec` now runs **`auto_paginate` → `align_wait_at_to_words`** **before** `compile_scene_class`, so both the LLM path (`scene-spec-generate`) and the compile-only path (`scene-compile`) get the same engine-driven pagination and word alignment.

## Dogfood (`docs/demos`)

- New segment **05** (`05-playwright-demos`) — long-form Manim explainer for the demo-video pipeline (TTS → timestamps → Manim → compose → Playwright/trace → demo-function).
- New maintainer hints (category B inputs):
  - **`hints/segment-05-topic.md`** — front-matter `docgen.segment` + `docgen.wiring` (visual → `manim`, narration prompt + hints, scene hints).
  - **`hints/playwright-demo-code.md`** — tools-and-roles reference for the segment 05 narrator/scene generator (intentionally tool-level, not algorithm-level).
- Generated outputs (category C; produced by tools, never hand-edited):
  - **`narration/05-playwright-demos.md`** (`docgen narration-generate --segment 05`)
  - **`audio/05-playwright-demos.mp3`** (`docgen tts --segment 05`)
  - **`animations/specs/05-playwright-demos.scene.yaml`** (`docgen scene-spec-generate --segment 05`) — engine emitted **2 pages × 4 rows** with per-row `wait_at` derived from Whisper words (no hand-carving).
  - **`animations/scenes.py` :: `PlaywrightDemosScene`** (`docgen scene-compile`)
  - **`recordings/05-playwright-demos.mp4`** (`docgen manim` + `docgen compose 05`).

The `manim-scene-specs.md` hint reflects the new contract: prefer pages over scaling, frame budget is enforced by `scene-spec-generate`, and `wait_at` is preferred when `timing.json` has Whisper word data.

## End-to-end refresh commands (reference)

From **`docs/demos`** with **`OPENAI_API_KEY`**:

```bash
# Bring docgen.yaml in sync with hint front matter (segment list, visual_map, wiring)
docgen --config docgen.yaml yaml-generate

# Per segment (example: 05)
docgen --config docgen.yaml narration-generate --segment 05
docgen --config docgen.yaml tts            --segment 05
docgen --config docgen.yaml timestamps     --segment 05
docgen --config docgen.yaml scene-spec-generate --segment 05   # auto-paginate + word align
docgen --config docgen.yaml scene-compile  animations/specs/05-playwright-demos.scene.yaml
docgen --config docgen.yaml manim          --scene PlaywrightDemosScene
docgen --config docgen.yaml compose 05
docgen --config docgen.yaml concat full-demo
docgen --config docgen.yaml validate
```

## Tests

New cases in **`tests/test_scene_spec.py`**:

- `test_compile_wait_at_emits_absolute_wait`
- `test_validate_rejects_wait_segment_and_wait_at_together`
- `test_layout_stack_budget_decreases_with_larger_title_font`
- `test_layout_budget_violations_flags_tall_single_page`
- `test_layout_budget_violations_accepts_split_pages`
- `test_layout_budget_violations_wide_row`
- `test_auto_paginate_splits_rows_into_pages_within_budget`
- `test_auto_paginate_leaves_fitting_single_page_untouched`
- `test_auto_paginate_preserves_explicit_pages_transitions`
- `test_align_wait_at_to_words_picks_first_mention_per_label`
- `test_align_wait_at_handles_multi_word_labels_and_advances_cursor`
- `test_align_wait_at_matches_label_to_inflected_word` (stem matcher)
- `test_align_wait_at_does_not_stem_match_short_tokens` (`TTS` stays strict)
- `test_align_wait_at_does_not_overwrite_existing_unless_asked`

Full `tests/test_scene_spec.py` suite: **20/20 green**.

## Lessons learned (process)

The early iterations of segment 05 kept regressing into hand-edits of the **generated** scene YAML to fix layout and timing. That is exactly the failure mode `.cursor/rules/no-asset-edits.mdc` (category C) is meant to prevent. The correct loop is:

> If a generated artifact is wrong, **fix the generator** (engine or hints), then re-run the tool — never patch the artifact in place.

Auto-pagination, word alignment, and stem matching all started life as one-off YAML edits. Promoting each one into `scene_spec.py` (with tests) means the same defect can never come back through the LLM-only path again.

## Follow-ups (optional)

- Teach `_rebuild-all.sh` / `generate-all` to re-run `scene-spec-generate` whenever a segment’s `narration.md` or `timing.json` changed (so `wait_at` values stay in sync without a manual step).
- Consider raising the LLM system prompt’s page-count default from “~3 rows” to use `layout_stack_budget` directly, so the model knows the actual budget rather than a heuristic.
- Investigate whether `align_wait_at_to_words` should also fall back to **fuzzy** matches (e.g. Levenshtein within 1) when stems still don’t match — useful for typos / hyphenation drift.
