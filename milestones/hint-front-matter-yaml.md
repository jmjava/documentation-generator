# Milestone: invalid hint front matter must not skip wiring

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/av-sync-anchor-keywords.md` (PR #101),
`milestones/yaml-generate-mappings.md` (PR #91)

## Problem

`parse_hint_docgen_front_matter` returned ``None`` on `YAMLError`, a
non-mapping root, or a non-mapping `docgen` key. `yaml-generate` then
treated the file as prose-only: no `visual_map` / narration / manim
wiring merge from that hint.

The **write** path (`update_hint_focus_paths`) already raises on invalid
YAML. The **read / merge** path did not, so a typo in `hints/*.md` front
matter silently dropped committed wiring instead of failing.

## Goal

Invalid YAML or a non-mapping `docgen` key is `ValueError` (CLI
`yaml-generate` already maps that to `ClickException`). Missing front
matter, empty front matter, and a mapping without `docgen` stay `None`.

## Done when

- [x] Invalid hint YAML raises instead of returning `None`.
- [x] `docgen:` as a list/scalar raises.
- [x] Non-docgen front matter (e.g. `title:`) still returns `None`.
- [x] `merge_defaults` surfaces the error from a broken `hints/*.md`.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- Hint files without `---` front matter remain optional prose.
- Empty `---` / `---` blocks remain `None`.
