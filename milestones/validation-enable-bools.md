# Milestone: validation enable flags must be YAML booleans

**Status:** Active  
**PR:** [#119](https://github.com/jmjava/documentation-generator/pull/119)  
**Depends on:** `milestones/validation-numeric-tunables.md` (PR #118),
`milestones/discovery-bool-flags.md` (PR #114)

## Problem

Nested validation numerics are typed. Enable flags still use Python
truthiness / ``bool()``:

1. Quoted ``validation.av_sync.enabled: "false"`` is a non-empty
   string, so the check **stayed on**.
2. ``manim.scene_lint: "false"`` kept scene lint on.
3. Integer ``subject_beat_coverage.enabled: 0`` disabled coverage via
   ``bool(0)`` instead of failing closed like other discovery bools.

YAML ``false`` / ``true`` already work.

## Goal

Fail closed at ``Config.from_yaml``. Present values of:

- ``manim.scene_lint``
- ``validation.layout.check_overlap``
- ``validation.av_sync.enabled`` / ``prefer_scene_spec_labels``
- ``validation.timing_sync.enabled``
- ``validation.scene_assets.enabled``
- ``validation.story_end.enabled``
- ``validation.subject_beat_coverage.enabled``

must be YAML booleans. Missing keys keep defaults.

## Done when

- [x] Present enable flags must be YAML booleans.
- [x] Tests for quoted ``"false"``, integer ``0``, and real YAML bools.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (686 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing which checks are soft in ``validate --pre-push``.
- Coercing ``"false"`` / ``0`` into booleans.
