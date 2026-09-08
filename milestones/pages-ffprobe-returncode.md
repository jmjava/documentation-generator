# Milestone: pages duration probes must honor ffprobe returncode

**Status:** Active  
**PR:** (this PR)  
**Depends on:** `milestones/ffprobe-returncode.md` (PR #135),
`milestones/pages-config-strings.md` (PR #111)

## Problem

PR #135 made compose / TTS / validate / local-timestamp duration probes
ignore stdout when ffprobe exits non-zero. Pages was left behind.

`PagesGenerator._probe_duration` / `_probe_concat_duration` still
`json.loads(out.stdout)` with no `returncode` check, then format a
badge. A failed probe that still printed JSON (or leftover stdout) can
stamp a **wrong duration** onto generated `index.html` instead of the
`"varies"` / `"concat"` fallback.

## Goal

Nonzero ffprobe is a failed probe. Keep the soft display fallbacks
(`"varies"` for segments, `"concat"` for full-demo cards) — do not
raise — but do not trust stdout on failure.

## Done when

- [ ] Segment / concat probes ignore stdout when `returncode != 0`
- [ ] Successful probes still render `~Mm Ss`
- [ ] Tests for leftover JSON on failure vs a real duration
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Validate `_check_streams` / `_check_drift` JSON probes (empty stdout
  already fails `json.loads` → failed check)
- Whisper prompt-cap `int(... or 0)` in timing enrichment (#142 out of
  scope; Config.from_yaml already gates those keys)
- Raising from `docgen pages` when ffprobe is missing
