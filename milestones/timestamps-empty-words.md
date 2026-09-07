# Milestone — Timestamps empty words

**Goal:** Local (and Whisper) timestamps must not write a `timing.json` block
with an empty `words` list. Heading-only narration and zero-duration audio
are errors, same contract as empty TTS.

**Branch / PR:** `cursor/timestamps-empty-words-2ccd`

Follows **[concat-segment-lists.md](concat-segment-lists.md)** (#84).
Closes another residual of issue **#56** (empty words → unpaced compile /
false-green `story_end`).

## Shipped

- [x] Local timestamps reject narration that is empty after markdown stripping
      (`TimestampError`, same as TTS)
- [x] `align_narration_to_audio` rejects duration `<= 0` (`AlignmentError`)
- [x] Local and Whisper extractors reject a block with no `words` before
      writing `timing.json`

## Not this milestone

- Empty `segments.all` still leaves `timing.json` unchanged (#78)
- Archived Playwright / Embabel / slides
