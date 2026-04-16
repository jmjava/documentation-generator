# Issue: Video Speed Adjustment via FFmpeg

**Milestone:** 4 — Playwright Test Video Integration
**Priority:** High (required for compose)
**Depends on:** Issue 3 (sync engine)

## Summary

Implement the FFmpeg video retiming logic that applies the speed adjustment factors computed by the sync engine, and integrate `type: playwright_test` into the existing `Composer`.

## Background

The sync engine (Issue 3) computes per-segment speed factors. This issue implements the actual video manipulation: splitting the source video into segments, applying `setpts` filters to each, and concatenating the result. The retimed video is then composed with narration audio via the existing `Composer._compose_simple` path.

## Acceptance Criteria

- [ ] Apply `setpts` filter for piece-wise speed adjustment
- [ ] Support variable speeds within a single video (different rates for different event windows)
- [ ] Preserve video quality during retiming (re-encode at source quality/CRF)
- [ ] Handle audio stripping from source video (Playwright videos may contain system audio or silence)
- [ ] Handle WebM input (Playwright default) — transcode to MP4 if needed
- [ ] Frame interpolation option for slowed-down segments (`minterpolate` filter) to improve quality at low FPS
- [ ] Add `type: playwright_test` handler in `compose.py`:
  ```python
  elif vtype == "playwright_test":
      video_path = self._playwright_test_path(vmap)
      sync_map = self._load_sync_map(seg_id)
      if sync_map:
          video_path = self._retime_video(video_path, sync_map)
      ok = self._compose_simple(seg_id, video_path, strict=strict)
  ```
- [ ] Configurable speed clamps: `min_speed_factor`, `max_speed_factor` in `docgen.yaml`

## Technical Notes

### Piece-wise speed adjustment approach

Rather than a single complex `setpts` expression, use the split-retime-concat approach:

1. Split source video at anchor points using `ffmpeg -ss -to`
2. Apply `setpts=PTS/factor` to each segment
3. Concat the retimed segments
4. Feed result to `_compose_simple` for audio muxing

### WebM handling

Playwright records in WebM by default. Two options:
- Transcode to MP4 early (simple, adds encoding time)
- Pass WebM through ffmpeg directly (works, but some filters behave differently)

Recommend: transcode to MP4 at collection time (in the test runner, Issue 2).

## Files to Create/Modify

- **Modify:** `src/docgen/compose.py` (add `playwright_test` handler, `_retime_video`)
- **Modify:** `src/docgen/config.py` (speed clamp config)
- **Create:** `tests/test_playwright_compose.py`
