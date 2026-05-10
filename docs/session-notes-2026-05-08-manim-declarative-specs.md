# Session notes — Declarative Manim scenes & dogfood refresh (May 8–9, 2026)

Canonical docs for day-to-day use: **`README.md`** (CLI table), **`AGENTS.md`** (agent context), **`docs/demos/README.md`** (dogfood). This file is a **change log / narrative** for one shipping slice.

## Problem

- **LLM-authored raw Manim** (`docgen scene-generate`, removed) often produced **bad 2D layout**: mobjects left at the origin, overlapping rows, fragile `next_to` chains, and occasional **validate** failures (unicode, `Text` font rules).
- **Narration length vs. visuals**: short on-screen motion while audio kept going (addressed by audio-tail injection and declarative specs + Whisper alignment).

## Solution (shipped)

1. **Declarative scene spec** — Module **`docgen.scene_spec`**: YAML schema (`segment_id`, `class_name`, `title`, `rows` of `_box`-like entries with `run_time`, optional `wait_segment`). **`compile_scene_class`** emits a `_TimedScene` subclass with **deterministic** placement (single-box rows `next_to` previous anchor; multi-box rows `VGroup(...).arrange(RIGHT, buff=...)` then `next_to`).
2. **`docgen scene-compile`** — Load `*.scene.yaml`, merge `timing_key` from `segment_names`, run **`lint_generated_block`** (subset of `manim_scene_lint`), inject into **`animations/scenes.py`** via existing markers.
3. **`docgen scene-spec-generate`** — OpenAI emits **YAML only** (same schema); IDs/class names are **normalized from CLI** so markers stay consistent. Optional **`--compile`**, **`--print-only`**, **`--output`**, **`manim_scene_generation.scene_spec_system_prompt`** overrides.
4. **Shared compile path** — **`linted_class_block_from_spec`** + **`inject_class_block_into_scenes_py`** used by both **`scene-compile`** and **`scene-spec-generate`**.
5. **Resilience** — **`docgen.openai_retry`**: rate-limit retries for TTS and chat-style calls where wired.

**`scene-generate`** (raw LLM Python) was **removed**; use **`scene-spec-generate`** + **`scene-compile`** for diagram rows, or hand-maintained classes for exceptional motion.

## Dogfood (`docs/demos`)

- Checked in **`animations/specs/01-overview.scene.yaml`**, **`02-init-scaffold.scene.yaml`**, **`03-wizard-gui.scene.yaml`** plus regenerated **`animations/scenes.py`**, **`timing.json`**, segment **`recordings/*.mp4`**, and **`full-demo.mp4`** (Git LFS).
- **Pre-push validate** required fixing **`narration/02-init-scaffold.md`**: removed **inline backticks** so **`narration_lint`** passes. Spoken audio for segment 02 may still match the *older* script until **`docgen tts --segment 02`** → **`timestamps`** → **`compose`** → **`concat full-demo`** is run again.

## End-to-end refresh commands (reference)

From **`docs/demos`** with **`OPENAI_API_KEY`**:

```bash
docgen --config docgen.yaml scene-spec-generate --segment 01 --compile --hint "…"
docgen --config docgen.yaml manim
docgen --config docgen.yaml compose
docgen --config docgen.yaml concat full-demo
docgen --config docgen.yaml validate
```

## Related PR / commits (main)

- **`704e011`** — `feat(docgen): declarative scene YAML, scene-spec-generate, and demos refresh`
- **`f141b5b`** — `fix(demos): remove backticks from 02-init-scaffold narration for TTS lint`

## Tests

- **`tests/test_scene_spec.py`**, **`tests/test_scene_spec_generate.py`** (mocked LLM; opt-in live test behind **`DOCGEN_RUN_LIVE_OPENAI=1`**), **`tests/test_openai_retry.py`**
- **`pytest.mark.integration`** registered in **`pyproject.toml`**

## Follow-ups (optional)

- Re-run **TTS** for segment **02** if spoken wording should match the lint-fixed narration.
- Teach **`_rebuild-all.sh`** (or **`generate-all`**) to prefer **`scene-spec-generate`** for Manim-only diagram segments when you want zero manual step.
