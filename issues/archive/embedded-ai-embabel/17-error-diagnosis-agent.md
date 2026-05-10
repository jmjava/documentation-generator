# Issue: Error Diagnosis Agent

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** Low
**Depends on:** Issue 12 (Embabel agents), Issue 14 or 15 (chat interface)

## Summary

Implement an Embabel agent that analyzes docgen pipeline errors and provides actionable diagnosis and fix suggestions. Integrates with the chat interface so users can ask "what went wrong?" and get specific, helpful answers.

## Background

Common docgen pipeline errors:
- **FREEZE GUARD**: video is much shorter than audio, causing excessive frozen frames
- **Missing audio**: TTS generation failed or was skipped
- **FFmpeg failures**: codec issues, missing files, timeout
- **Playwright timeouts**: capture script or test runs too long
- **VHS errors**: tape commands fail in the real shell
- **Validation failures**: A/V drift, OCR errors, narration lint issues

Currently, users must manually read error messages and figure out fixes. The diagnosis agent understands docgen's pipeline and can map error patterns to specific remediation steps.

## Acceptance Criteria

- [ ] Embabel `DebugAgent` that analyzes pipeline errors:
  - Input: error log text, segment ID, pipeline stage, relevant config
  - Output: diagnosis (what went wrong), suggestion (how to fix it), optional auto-fix
- [ ] Handles all common error types:
  | Error | Diagnosis | Suggestion |
  |-------|-----------|------------|
  | FREEZE GUARD | Manim scene is 5s shorter than narration | "Add `self.wait(5)` at end of scene, or run `docgen generate-all --retry-manim`" |
  | Missing audio | TTS failed for segment 03 | "Check OPENAI_API_KEY, run `docgen tts --segment 03`" |
  | FFmpeg timeout | Compose timed out at 300s | "Increase `compose.ffmpeg_timeout_sec` or check video file integrity" |
  | Playwright timeout | Script exceeded 120s | "Increase `playwright.timeout_sec` or optimize the capture script" |
  | A/V drift | Video 2.8s longer than audio | "Video needs trimming; check visual_map source duration" |
  | OCR error | "command not found" detected in frame | "VHS tape has a failing command; check line 15 of the tape" |
- [ ] Can auto-fix common issues when given permission:
  - Rerun TTS for a failed segment
  - Retry Manim with cache cleared
  - Increase timeout and retry
- [ ] Integrates with `docgen validate` output for proactive suggestions
- [ ] Python-side wrapper for invoking via chat or CLI

## Files to Create/Modify

- **Modify:** `docgen-agent/` (add DebugAgent if using Embabel)
- **Create:** `src/docgen/error_diagnosis.py` (Python-side integration and fallback logic)
- **Create:** `tests/test_error_diagnosis.py`
