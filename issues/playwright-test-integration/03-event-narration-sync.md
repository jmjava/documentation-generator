# Issue: Event-to-Narration Synchronizer

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** High (core sync logic)
**Depends on:** Issue 1 (trace extractor), Issue 2 (test runner)

## Summary

Create `playwright_sync.py` — the core synchronization engine that aligns narration audio timing with Playwright browser events extracted from test traces. This is analogous to `tape_sync.py` for VHS and `scenes.py` timing for Manim, but operates on continuous video rather than discrete commands.

## Background

The fundamental challenge: a Playwright test runs at its own pace (e.g., clicks at 1.2s, 3.4s, 5.1s), but the narration discusses those actions at different times (e.g., "now we fill in the email" starts at 2.0s, "click submit" at 6.0s). We need to warp the video timeline so the visual actions align with the spoken narration.

### Sync Algorithm

```
Input:
  events[]  = [{t: 1.2, action: "fill", selector: "#email"}, ...]   # from events.json
  timing    = {segments: [...], words: [...]}                         # from timing.json
  anchors[] = [{narration_anchor: "fill in email", action: "fill"}]  # from config

Algorithm:
  1. For each anchor, find matching event by action + selector
  2. For each anchor, find matching narration timestamp by fuzzy text search in words[]
  3. Build desired_time[] (narration) and actual_time[] (video) pairs
  4. Compute speed factors between consecutive anchor pairs:
     speed[i] = (desired[i+1] - desired[i]) / (actual[i+1] - actual[i])
  5. Clamp speed factors to [0.25, 4.0]
  6. Generate ffmpeg setpts filter for piece-wise speed adjustment
  7. Output sync_map.json + retimed video
```

## Acceptance Criteria

- [ ] Load `events.json` + `timing.json` and match anchors to events
- [ ] Fuzzy keyword matching between narration text and event descriptions
- [ ] Compute per-segment speed adjustment factors
- [ ] Generate `sync_map.json`:
  ```json
  {
    "anchors": [
      {"event_t": 1.2, "narration_t": 2.0, "action": "fill", "text": "fill in the email"},
      {"event_t": 3.4, "narration_t": 6.0, "action": "click", "text": "click submit"}
    ],
    "speed_segments": [
      {"start": 0.0, "end": 1.2, "factor": 1.67},
      {"start": 1.2, "end": 3.4, "factor": 0.55}
    ]
  }
  ```
- [ ] Support sync strategies:
  - `stretch` — adjust video speed to match narration (default)
  - `cut` — trim idle periods from video
  - `pad` — freeze key frames to extend short segments
- [ ] CLI: `docgen sync-playwright [--segment 03] [--dry-run] [--strategy stretch]`
- [ ] Validation: warn when event count doesn't match anchor count
- [ ] Fallback: even distribution when no anchors match (same as VHS default)

## Technical Notes

The speed factor computation is conceptually identical to how `tape_sync.py` distributes `duration / n_blocks` across VHS Type/Enter/Sleep blocks, but applied to continuous video timecodes rather than discrete sleep values.

FFmpeg `setpts` filter for variable-speed playback:
```
setpts='if(lt(PTS,1.2),PTS*1.67,if(lt(PTS,3.4),(PTS-1.2)*0.55+2.0,...))'
```

For complex speed profiles, it may be cleaner to split, retime, and concat rather than build one complex setpts expression.

## Files to Create/Modify

- **Create:** `src/docgen/playwright_sync.py`
- **Modify:** `src/docgen/cli.py` (add `sync-playwright` command)
- **Create:** `tests/test_playwright_sync.py`
