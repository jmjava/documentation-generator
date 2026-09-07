# Milestone: Manim bootstrap timing loaders must type timing.json

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/timing-inner-lists.md` (PR #127),
`milestones/wizard-json-object.md` (PR #129)

## Problem

Library ``load_bundle_timing`` now rejects non-object stems and non-array
``words`` / ``segments``. Compiled ``scenes.py`` still used:

```python
data.get(segment_key, {}).get("segments", [])
block = data.get(segment_key) or {}
```

A list stem raises ``AttributeError`` at Manim ``construct()``. A string
``words`` field is coerced to empty and the board is unpaced.

``scene-compile`` did not refresh those helpers.

## Goal

Bootstrap ``_load_timing`` / ``_load_timing_words`` raise ``TypeError`` on
corrupt stem / inner types. Missing file or missing stem still returns
``[]``. ``refresh_bootstrap_helpers`` and ``helper_api_violations`` treat
the old bodies as stale.

## Done when

- [ ] New helpers reject list stems and non-array ``words`` / ``segments``
- [ ] ``refresh_bootstrap_helpers`` rewrites stale loaders
- [ ] ``helper_api_violations`` flags stale loaders
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (helper change; meets baseline, no bump)

## Out of scope

- Changing the corrupt-JSON → empty reset in wizard ``load_state``
- Requiring numeric ``start`` / ``end`` on every word row
