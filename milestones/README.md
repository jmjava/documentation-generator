# Milestones

**Consumers:** See **[upstream-dogfood.md](upstream-dogfood.md)** — notes for
repositories that install `docgen` and maintain their own demo bundle. The
library no longer ships an in-repo dogfood; consumers are the integration test
of record.

**Active:** **[wizard-exclude-lists.md](wizard-exclude-lists.md)** —
`wizard.exclude_patterns` / `scan_extensions` must be string lists, not scalars.

**Shipped:**
- **[timestamps-merge-stems.md](timestamps-merge-stems.md)** — CLI `timestamps`
  merges stems into existing `timing.json` instead of wiping extra keys (#93).
- **[asset-graph-timing.md](asset-graph-timing.md)** — wizard freshness must
  not treat corrupt `timing.json` as a missing timestamps entry (#92).
- **[yaml-generate-mappings.md](yaml-generate-mappings.md)** — `yaml-generate`
  merge/discover must not replace a list/scalar `visual_map` or narration/manim
  block with `{}` (#91).
- **[context-path-lists.md](context-path-lists.md)** — `pages.segments` and
  narration/manim context path lists must be typed (#90).
- **[timing-json-parse.md](timing-json-parse.md)** — corrupt `timing.json`
  must not be treated as empty words at compile/validate (#89).
- **[lint-empty-narration.md](lint-empty-narration.md)** — lint / validate fail
  when narration has no spoken prose after markdown stripping (#88).
- **[segment-id-strings.md](segment-id-strings.md)** — unquoted YAML `01`
  must not become integer segment ids (#87).
- **[visual-map-row-types.md](visual-map-row-types.md)** — `visual_map` rows
  and `pages.segments` entries must be mappings; unknown compose `type`
  fails closed (#86).
- **[timestamps-empty-words.md](timestamps-empty-words.md)** — heading-only
  / empty-word timestamps fail closed (#85).
- **[concat-segment-lists.md](concat-segment-lists.md)** — concat targets
  must be lists of segment ids; pages extra_links items must be mappings
  (#84).
- **[config-mapping-keys.md](config-mapping-keys.md)** — nested `docgen.yaml`
  mapping/list keys must not traceback; lint/compose empty-all must not
  succeed (#83).
- **[manim-lint-config.md](manim-lint-config.md)** — missing `scenes.py`
  fails validate; invalid `docgen.yaml` is `ConfigError`; TTS empty-all
  fails (#82).
- **[wizard-narration-paths.md](wizard-narration-paths.md)** — wizard
  generate-narration must not drop missing sources; timestamps must not wipe
  corrupt `timing.json` (#81).
- **[validate-fail-closed.md](validate-fail-closed.md)** — validate
  narration/timing skips, empty Manim lists, missing context paths.
- **[scene-compile-pace.md](scene-compile-pace.md)** — paced `scene-compile`
  requires timing words; `yaml-generate` keeps committed Manim rows.
- **[timestamps-fail-closed.md](timestamps-fail-closed.md)** — timestamps,
  concat, Anthropic `base_url`, and remaining CLI/wizard silent-success paths.
- **[pipeline-fail-closed.md](pipeline-fail-closed.md)** — `generate-all` /
  `yaml-generate` fail closed (preserve still/recording wiring; no silent
  compose/validate skip).
- **[multi-host-ai-hardening.md](multi-host-ai-hardening.md)** — Cloud /
  local Cursor / Claude Code keys, `--repo` clone cache, fail-closed chat.

**Not in this milestone:** archived slides / i18n / Playwright / Embabel
roadmaps under [archive/](archive/) (Playwright was removed from the product;
Embabel is a future sketch).

**Archived roadmaps:** [archive/](archive/) — older write-ups kept for history;
not the day-to-day execution list.

**Session notes (ad hoc):** e.g. declarative Manim work under
`docs/session-notes*.md` when present.
