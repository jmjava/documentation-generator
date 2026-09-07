# Milestone: wizard JSON bodies must parse

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/wizard-source-paths.md` (PR #131)

## Problem

``request_json_object`` used Flask ``get_json(silent=True)``. Missing bodies
and **invalid JSON** both returned ``None``, which became ``{}``. A POST of
``{not-json`` looked like an empty object and could write ``.docgen-state.json``
or run generate-narration with no fields.

JSON ``null`` was also treated as a missing body.

## Goal

Empty / whitespace-only bodies stay ``{}``. Invalid JSON raises
``WizardError``. JSON ``null`` is rejected as a non-object (same as a list).

## Done when

- [ ] Invalid JSON POST returns 400 and does not write state
- [ ] JSON ``null`` returns 400
- [ ] Empty body still succeeds as ``{}``
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Wizard ``except Exception`` around ``narration_topic_label``
