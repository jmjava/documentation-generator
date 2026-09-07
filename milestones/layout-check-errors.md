# Milestone: layout check crashes must not skip as success

**Status:** Shipped  
**PR:** #97  
**Depends on:** `milestones/validate-fail-closed.md`,
`milestones/manim-unsafe-unicode.md` (PR #96)

## Problem

`Validator._check_layout` already skips when tesseract is missing
(`passed=True`, same as OCR). After tesseract is present, any unexpected
exception from `LayoutValidator.validate_video` (TypeError, KeyError, bad
OCR payload, etc.) returned **`passed=True`** with
`"Layout check error (skipped): …"`.

`_check_streams` and `_check_drift` already return `passed=False` on the
same kind of crash. Layout is in `--pre-push` `soft_checks`, so a crash
printed as a skip and the command still said **All checks passed**.

## Goal

Treat layout runtime errors as a failed check. Tesseract-not-installed
remains a skip.

## Done when

- [x] Unexpected exceptions in `_check_layout` return `passed=False`.
- [x] Tesseract missing still skips with `passed=True`.
- [x] Tests for the crash path and the tesseract-skip path.
- [x] `ruff check src/ tests/`
- [x] `pytest tests/`
- [x] `docgen benchmark` (no clock change)

## Out of scope

- Layout / OCR / av_sync remain **soft** in `validate --pre-push`.
- Tesseract missing still skips OCR, layout, and av_sync.
- `av_sync` swallowing unreadable `*.scene.yaml` is a separate hole.
