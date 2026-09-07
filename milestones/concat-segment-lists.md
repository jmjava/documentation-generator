# Milestone — Concat segment lists and pages extra_links

**Goal:** `concat.<name>` must be a YAML list of segment ids (a string must
not be iterated as characters). `pages.extra_links` items must be mappings.

**Branch / PR:** `cursor/concat-segment-lists-2ccd`

Follows **[config-mapping-keys.md](config-mapping-keys.md)** (#83).

## Shipped

- [x] `concat.<target>` that is a string/scalar raises `ConfigError` at load
      and `ConcatError` in `ConcatBuilder`
- [x] `pages.extra_links` items that are not mappings raise instead of
      `TypeError` on `lnk["href"]`
- [x] `docgen pages` maps that `RuntimeError` to `ClickException`

## Not this milestone

- Empty `concat:` map remains a no-op (bundles that do not stitch a full demo)
- Archived Playwright / Embabel / slides
