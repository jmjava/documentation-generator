# Milestone: wizard POST bodies must be JSON objects

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/wizard-state-segments.md` (PR #128)

## Problem

PR #128 typed ``POST /api/state``. Other wizard POST/PUT handlers still
did ``request.json or {}`` then ``.get``. A JSON **array** is truthy, so
the default never applied and Flask raised ``AttributeError``.

``bool(data.get("with_manim", False))`` treated the string ``"false"`` as
true.

## Goal

Every wizard JSON body must be an object (missing body still ``{}``).
Boolean fields (``with_manim``, ``update_requirements``, ``also_manim``,
``yaml_generate``, ``llm_scene_spec``) must be JSON booleans when present.

## Done when

- [ ] List / scalar POST bodies return 400 on all wizard JSON endpoints
- [ ] String ``"false"`` / ``"true"`` for bool fields return 400
- [ ] Existing object-body tests still pass
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Invalid JSON still becomes ``{}`` via ``get_json(silent=True)``
- Wizard ``except Exception`` around ``narration_topic_label``
