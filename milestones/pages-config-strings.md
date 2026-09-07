# Milestone: pages docs_dir / title / extra_links must be typed

**Status:** Active  
**PR:** pending  
**Depends on:** `milestones/generation-segment-strings.md` (PR #110),
`milestones/path-config-strings.md` (PR #109),
`milestones/concat-segment-lists.md` (PR #84)

## Problem

`env_file` / `dirs.*` are already strings at config load. Pages keys
were not:

1. **`pages.docs_dir` / `demos_subdir`** — a YAML list Path-joined when
   writing `index.html` / `pages.yml` (`Path / list` TypeError).
2. **`pages.title` / `subtitle` / `repo_url`** — a list was interpolated
   into HTML as `"['Demo Videos']"`.
3. **`pages.segments.<id>.title` / `description`** — same HTML
   interpolation; a non-mapping row only failed at `pages` generate
   (`RuntimeError`), not at config load.
4. **`pages.extra_links`** — a non-list or non-mapping item only failed
   at generate; `href` / `label` were untyped.

## Goal

Fail closed at `Config.from_yaml`. Missing keys still use defaults
(`docs`, `demos`, `"Demo Videos"`). Empty `title` / `subtitle` /
`repo_url` remain allowed.

## Done when

- [x] Present `pages.docs_dir` / `demos_subdir` must be non-empty YAML
      strings.
- [x] Present `pages.title` / `subtitle` / `repo_url` must be YAML
      strings (empty allowed).
- [x] `pages.segments` rows must be mappings; present `title` /
      `description` must be YAML strings (empty allowed).
- [x] `pages.extra_links` must be a list of mappings with non-empty
      `href` strings.
- [x] Tests for list / non-mapping values.
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change)

## Out of scope

- `wizard.default_guidance` type gating is separate.
- Unknown `pages.extra_links` keys besides `href` / `label` are ignored.
