# Milestone: wizard exclude/scan lists must not be scalars

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/yaml-generate-mappings.md` (PR #91),
`milestones/config-mapping-keys.md` (PR #83)

## Problem

`wizard.exclude_patterns` is a list of glob strings. A YAML string was:

1. **Wiped** by `yaml-generate` `merge_defaults` (`ex = []`).
2. **Iterated as characters** by wizard `/api/scan` (`fnmatch` over `"a"`, `"r"`, …).

`wizard.scan_extensions` as a string similarly overwrote the default extension
tuple in `wizard_config` and scanned the wrong files.

## Goal

Fail closed at `Config.from_yaml` (`string_list_block`) and in `merge_defaults`
(present non-list raises `ValueError`). Missing keys still default.

## Done when

- [x] `wizard.exclude_patterns` / `wizard.scan_extensions` if present must be
      YAML lists of strings.
- [x] `merge_defaults` does not replace a string `exclude_patterns` with `[]`.
- [x] Tests for string exclude_patterns and scan_extensions.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Empty `exclude_patterns: []` remains allowed (archive dirs are still skipped
  via `is_under_archive_dir`).
- Wizard `.docgen-state.json` corrupt still resets to empty.
