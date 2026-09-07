# Milestone: wizard state segments must be objects

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/timing-inner-lists.md` (PR #127)

## Problem

``load_state`` accepts any JSON object. ``GET /api/segments`` then does
``state.get("segments", {}).get(seg_id, {})``. A list, string, or
per-id non-object under ``segments`` raises ``AttributeError`` (500
traceback). ``POST /api/state`` writes that payload unchanged.

Corrupt JSON / a non-object root still reset to ``{"segments": {}}``
so a broken file does not brick the wizard.

## Goal

When ``segments`` is present, it must be a JSON object whose values
are objects. ``POST /api/state`` rejects a non-object body and invalid
``segments`` with 400. ``GET`` on a corrupt-typed file returns 500 with
the parse error (not ``AttributeError``).

## Done when

- [ ] ``load_state`` raises ``WizardError`` on list / scalar ``segments``
- [ ] per-id non-object rows raise
- [ ] missing / null ``segments`` still means ``{}``
- [ ] corrupt JSON still resets to empty (existing contract)
- [ ] ``POST /api/state`` rejects a list body and list ``segments``
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Changing the corrupt-JSON → empty reset
- Wizard ``except Exception`` around ``narration_topic_label``
