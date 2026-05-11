# Narration scripts (TTS source)

These Markdown files are the spoken script for demo segments.
`docgen tts` turns them into `audio/*.mp3`.

## Voice-first editing

TTS reads what you write literally. Tips:

- Use spoken URLs: "GET slash api slash data" not `GET /api/data`
- Spell out abbreviations the first time
- No markdown formatting — plain spoken English only
- Run `docgen lint` to check for leaked metadata before TTS

## After edits

Regenerate **audio** and **timestamps** when you change meaning or length of the script so `animations/timing.json` stays aligned with what TTS actually speaks (Whisper drives Manim pacing).

```bash
docgen tts --segment <id>    # or docgen tts for all
docgen timestamps
docgen rebuild-after-audio   # Manim + compose + validate + concat
```
