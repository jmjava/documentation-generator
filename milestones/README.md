# Milestones

**Consumers:** See **[upstream-dogfood.md](upstream-dogfood.md)** — notes for
repositories that install `docgen` and maintain their own demo bundle. The
library no longer ships an in-repo dogfood; consumers are the integration test
of record.

**Active:** **[validate-fail-closed.md](validate-fail-closed.md)** — validate
and remaining CLI skips must not pass listed segments with no narration,
untimed paced specs, or dropped context files.

**Shipped:**
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
