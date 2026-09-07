# Milestone: `manim.unsafe_unicode` must be a list at config load

**Status:** Shipped  
**PR:** #96  
**Depends on:** `milestones/validation-list-keys.md` (PR #95),
`milestones/config-mapping-keys.md` (PR #83)

## Problem

`manim.unsafe_unicode` as a YAML string already raised `ConfigError` when the
property was **read** (validate / scene-spec-generate). `Config.from_yaml` did
not touch it, so `yaml-generate`, `tts`, and other commands could load a bad
file. A string would also have been iterated as characters inside unicode lint
if anything called the property after a bypass.

## Goal

Evaluate `manim_unsafe_unicode` during `Config.from_yaml` (same as
`manim.scenes`). Use `string_list_block` so items must be YAML strings.

## Done when

- [x] `manim.unsafe_unicode` if present must be a YAML list of strings.
- [x] Missing / null still uses the built-in Pango fallback character list.
- [x] Empty list still disables the unicode lint (`[]`).
- [x] Test for a string value at `Config.from_yaml`.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- The default character list itself is unchanged.
