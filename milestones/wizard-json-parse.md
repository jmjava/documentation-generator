# Milestone: wizard JSON bodies must parse

**Status:** Shipped  
**PR:** [#132](https://github.com/jmjava/documentation-generator/pull/132)  
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

- [x] Invalid JSON POST returns 400 and does not write state
- [x] JSON ``null`` returns 400
- [x] Empty body still succeeds as ``{}``
- [x] `ruff check src/ tests/`
- [x] `pytest tests/` (758 passed, 1 skipped)
- [x] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Wizard ``except Exception`` around ``narration_topic_label``
