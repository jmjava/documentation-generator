# Milestone — Nested config mappings and empty lint/compose

**Goal:** Nested `docgen.yaml` keys that must be mappings or lists must not
traceback (`AttributeError` / `TypeError`). `docgen lint` and `docgen compose`
must not exit 0 when there are no segments to process.

**Branch / PR:** `cursor/config-mapping-keys-2ccd`

Follows **[manim-lint-config.md](manim-lint-config.md)** (#82).

## Shipped

- [x] `dirs`, `segments`, `visual_map`, `tts`, `manim`, `validation`, and
      related keys reject list/scalar values (`ConfigError`)
- [x] `segments.all` / `segments.default` must be YAML lists (a string is not
      iterated as characters)
- [x] Null mapping keys still mean “use defaults”
- [x] `docgen lint` with empty `segments.all` (no `--segment`) is an error
- [x] `docgen compose` with no remaining segment ids is an error

## Not this milestone

- Missing recordings stay a pre-push **warning**
- `timestamps` with empty `segments.all` still leaves `timing.json`
      unchanged (#78)
- Archived Playwright / Embabel / slides
