# Milestone: wizard source_paths and string fields must be typed

**Status:** Shipped  
**PR:** [#131](https://github.com/jmjava/documentation-generator/pull/131)  
**Depends on:** `milestones/wizard-json-object.md` (PR #129),
`milestones/bootstrap-timing-helpers.md` (PR #130)

## Problem

PR #129 required wizard bodies to be JSON objects. ``source_paths`` still
used ``list(data.get("source_paths") or [])``. A string is iterable, so
``"README.md"`` became ``['R','E','A',…]`` and looked like missing files
instead of a type error. A list ``guidance`` / ``text`` later called
``.strip()`` and raised ``AttributeError``.

Focus ``paths`` items were ``str()``-coerced (an integer ``1`` became
``"1"``).

## Goal

``source_paths`` (when present) must be a JSON array of strings. Missing
/ null still means ``[]`` (hint-path fallback). ``guidance``,
``segment_name``, ``revision_notes``, ``current_narration``, ``mode``,
``topic_label``, ``segment_id``, and PUT ``text`` must be JSON strings
when present. Focus ``paths`` items must be strings.

## Done when

- [x] String ``source_paths`` returns 400 (not char-split)
- [x] Non-string list items return 400
- [x] List ``guidance`` / ``text`` return 400
- [x] Focus path integers return 400
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (755 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Invalid JSON still becomes ``{}`` via ``get_json(silent=True)``
- Wizard ``except Exception`` around ``narration_topic_label``
