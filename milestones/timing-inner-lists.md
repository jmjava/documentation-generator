# Milestone: timing.json words/segments must be object arrays

**Status:** Active  
**PR:** [#127](https://github.com/jmjava/documentation-generator/pull/127)  
**Depends on:** `milestones/timing-stem-objects.md` (PR #126)

## Problem

PR #126 required each ``timing.json`` stem to be a JSON object. Inner
``words`` / ``segments`` were still untyped. A stem like
``{"words": "x"}`` or ``{"words": ["hello"]}`` then:

1. Compile / ``scene-spec-generate`` coerced a non-list to ``[]``
   (``pace: none`` compiled as if timestamps had never been run).
2. A list of non-objects kept LLM ``wait_word`` indices and later
   crashed Manim on ``.get("start")``.
3. ``sync_audio_tail_waits_in_scenes`` treated a truthy non-list
   ``segments`` string as present and tried to patch ``scenes.py``.

## Goal

When ``words`` or ``segments`` is present and not null, it must be a
JSON array of objects. Missing / null / ``[]`` stay allowed (empty still
means no timings; paced compile already fails).

## Done when

- [x] ``load_bundle_timing`` rejects non-array ``words`` / ``segments``
- [x] ``load_bundle_timing`` rejects non-object array items
- [x] ``pace: none`` compile fails with the parse error (not silent empty)
- [x] validate / wizard / ``extract_all`` surface the error and do not
      rewrite the file
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (734 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Empty ``segments.all`` still leaves ``timing.json`` unchanged (#78)
- Requiring numeric ``start`` / ``end`` on every word row
- Bootstrap ``_load_timing`` helpers inside compiled ``scenes.py``
