# Milestone: `visual_map` row types and pages segment entries

**Status:** Shipped  
**PR:** #86  
**Depends on:** `milestones/config-mapping-keys.md` (PR #83)

## Problem

`visual_map` rows and `pages.segments` entries are assumed to be mappings. Invalid
types are treated as empty slots or crash with `AttributeError`.

1. **`visual_map` scalar / list row** — `_visual_entry_type` returns `""` for a
   non-dict, so `01: FirstScene` looks like an empty manim slot.
   `discover_visual_map` then overwrites it. `Config.from_yaml` never rejected it.
2. **Unknown compose `type`** — `Composer.compose_segments` printed a skip
   message and returned instead of failing. A typo (`type: vhs`) produced no
   video and exit 0 if that was the only segment.
3. **`pages.segments.<id>` as a string** — `_resolve_segments_cfg` called
   `.get("title")` on the value and traceback'd.

## Goal

Fail closed at config load, yaml-generate discovery, compose, and pages.

## Done when

- [x] `Config.from_yaml` raises `ConfigError` when `visual_map.<sid>` is not a mapping.
- [x] `discover_visual_map` raises `ValueError` (CLI → `ClickException`) for the same.
- [x] Unknown compose `type` raises `ComposeError`; `docgen compose` maps it to `ClickException`.
- [x] `pages.segments.<id>` must be a mapping; otherwise `RuntimeError` (CLI → `ClickException`).
- [x] Tests: `test_from_yaml_string_visual_map_row_raises`,
      `test_discover_visual_map_rejects_non_mapping_row`,
      `test_compose_unknown_visual_type_raises`,
      `test_cli_compose_unknown_visual_type_is_click_error`,
      `test_index_html_rejects_non_mapping_pages_segments`.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Empty `visual_map` (`{}`) remains allowed.
- Missing `visual_map` entries still print SKIP (unmapped), same as today.
- Known compose types stay `manim`, `still`, `image`, and `mixed`.
