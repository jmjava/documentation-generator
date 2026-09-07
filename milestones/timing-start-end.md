# Milestone: timing.json word/segment start and end must be numbers

**Status:** Active  
**PR:** [#134](https://github.com/jmjava/documentation-generator/pull/134)  
**Depends on:** `milestones/timing-inner-lists.md` (PR #127),
`milestones/bootstrap-timing-helpers.md` (PR #130),
`milestones/wizard-path-ref.md` (PR #133)

## Problem

PR #127 required ``words`` / ``segments`` to be arrays of objects. Each row
still used ``float(row.get("start", 0.0))``.

``start: true`` became ``1.0`` because ``bool`` is a subclass of ``int``.
A missing ``start`` waited until ``0.0`` and dumped the board. A string
``"0.5"`` looked like a timestamp instead of a type error.

## Goal

When a ``words`` / ``segments`` row is present, ``start`` and ``end`` must
be JSON numbers (``int`` or ``float``, not ``bool``). Missing / null / string
rows fail closed in ``load_bundle_timing`` and in Manim ``_load_timing`` /
``_load_timing_words``. Empty ``[]`` / missing / null lists stay allowed.

``scene-compile`` refreshes bootstrap helpers that only typed objects.

## Done when

- [x] ``load_bundle_timing`` rejects missing / null / bool / string ``start`` / ``end``
- [x] Bootstrap loaders reject the same at Manim render
- [x] Stale object-only loaders are refreshed
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (766 passed, 1 skipped)
- [x] `docgen benchmark` (helper change; meets baseline, no bump)

## Out of scope

- ``wait_until_word`` still swallows ``TypeError`` / ``ValueError`` after load
- Requiring ``end >= start``
