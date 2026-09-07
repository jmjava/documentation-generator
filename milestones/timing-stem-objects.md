# Milestone: timing.json per-stem values must be objects

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/timing-json-parse.md` (PR #89),
`milestones/cli-segments-all.md` (PR #125)

## Problem

``load_bundle_timing`` required the ``timing.json`` **root** to be a JSON
object. Per-stem values were untyped. A list, string, number, or null under
a stem then:

1. ``scene-spec-generate`` / compile treated the stem as missing words
   (``pace: none`` compiled as if timestamps had never been run).
2. ``sync_audio_tail_waits_in_scenes`` called ``.get`` on a list and
   raised ``AttributeError``.
3. Wizard freshness treated a list stem as a present timestamps entry.

## Goal

Every present stem value must be a JSON object. Missing ``timing.json``
is still ``{}``. A present non-object stem raises ``TimestampError``.

## Done when

- [ ] ``load_bundle_timing`` rejects list / string / number / null stems
- [ ] paced and ``pace: none`` compile fail with the parse error
- [ ] validate ``timing_sync`` and scene-asset checks surface the error
- [ ] ``extract_all`` / wizard statuses do not merge or treat list stems
      as valid
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Empty ``segments.all`` still leaves ``timing.json`` unchanged (#78)
- Inner ``words`` / ``segments`` list typing (paced compile already
  fails when ``words`` is missing)
- Bootstrap ``_load_timing`` helpers inside compiled ``scenes.py``
  (Manim render still uses ``json.loads``; compile/validate gate first)
