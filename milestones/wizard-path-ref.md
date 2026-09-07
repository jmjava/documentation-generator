# Milestone: wizard open-bundle path and tool/update ref must be strings

**Status:** Active  
**PR:** (pending)  
**Depends on:** `milestones/wizard-json-parse.md` (PR #132)

## Problem

PR #131 typed wizard prose fields and ``source_paths``. ``POST /api/open-bundle``
and ``POST /api/tool/update`` still used ``str(data.get(...) or default)``.

``path: ["/tmp/bundle"]`` became ``"['/tmp/bundle']"`` and looked like a
missing yaml file. ``ref: true`` became ``"True"``, which matches the git-ref
allowlist and would ``pip install`` from that ref. ``ref: 0`` / ``ref: false``
are falsy, so they silently fell through to ``"main"``.

## Goal

``path`` and ``ref`` must be JSON strings when present. Missing / null ``path``
still means empty (existing ``path is required``). Missing / null ``ref`` still
defaults to ``main``. Empty ``ref`` still defaults to ``main``.

## Done when

- [ ] List / bool / number ``path`` returns 400
- [ ] Bool / number / list ``ref`` returns 400 (does not pip-install)
- [ ] Missing ``ref`` still defaults to ``main``
- [ ] `ruff check src/ tests/`
- [ ] `pytest tests/`
- [ ] `docgen benchmark` (no clock change; meets baseline)

## Out of scope

- Wizard ``except Exception`` around ``narration_topic_label``
- Focus ``paths`` missing vs empty (already typed as a list of strings)
