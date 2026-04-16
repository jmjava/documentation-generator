# Issue: Narration Anchor Auto-Detection

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** Low (nice-to-have)
**Depends on:** Issues 1, 3

## Summary

Automatically detect narration anchors by cross-referencing Playwright action metadata (selectors, URLs, typed text) with the narration transcript, reducing the manual configuration needed for event-to-narration sync.

## Acceptance Criteria

- [ ] Analyze Playwright actions to extract descriptive keywords:
  - `click "button[type=submit]"` → "submit", "button"
  - `fill "#email"` → "email"
  - `goto "/dashboard"` → "dashboard"
  - `click "[data-testid=save-btn]"` → "save"
- [ ] Cross-reference extracted keywords with narration text (word-level timestamps from Whisper)
- [ ] Use Whisper word-level timestamps for precise alignment
- [ ] Generate suggested anchor mappings:
  ```json
  {
    "auto_anchors": [
      {"event_idx": 0, "action": "fill", "keyword": "email", "narration_word_idx": 12, "narration_t": 2.1, "confidence": 0.85},
      {"event_idx": 1, "action": "click", "keyword": "submit", "narration_word_idx": 28, "narration_t": 5.8, "confidence": 0.92}
    ]
  }
  ```
- [ ] Fallback: evenly distribute events across narration duration when no anchors match
- [ ] Confidence scoring for each match (exact word match > substring > semantic similarity)
- [ ] CLI: `docgen suggest-anchors --segment 03` to preview auto-detected mappings
- [ ] Interactive mode: present suggestions and let user confirm/override

## Technical Notes

Keyword extraction from selectors uses heuristics:
- `#email` → strip `#`, split camelCase → "email"
- `[data-testid=save-btn]` → extract value, strip `-btn` suffix → "save"
- `button:has-text("Submit")` → extract text content → "Submit"
- URL paths: `/dashboard/settings` → "dashboard", "settings"

The confidence scoring considers:
- Exact word match in narration transcript (high)
- Partial match or synonym (medium)
- Positional heuristic: events and narration words should be in the same order (boost)

## Files to Create/Modify

- **Create:** `src/docgen/anchor_detection.py`
- **Modify:** `src/docgen/cli.py` (add `suggest-anchors` command)
- **Create:** `tests/test_anchor_detection.py`
