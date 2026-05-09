# Segment 05 context — tools and roles (not algorithms)

Plain reference for **narration-generate** / **scene-spec-generate**. Stay at **which tool does what**; do not narrate implementation detail from this file.

---

## Long-form Manim segments (this bundle’s explainer clips)

| Stage | Tool / command | Role |
|--------|----------------|------|
| Script | `docgen` narration markdown | What gets spoken |
| Voice | `docgen tts` + OpenAI speech | Turn script into one MP3 |
| Timing | `docgen timestamps` | Uses hosted speech-to-text so beats match the real recording |
| Picture | Manim (`docgen manim`) | Render the diagram against that timing |
| Final file | `docgen compose` + ffmpeg | Put Manim picture and narration audio in one MP4 |
| QA | `docgen validate` | Catch A/V length drift and similar issues |

---

## Short Playwright tutorial clips

| Stage | Tool / command | Role |
|--------|----------------|------|
| Test run | Playwright via `docgen demo-function` | Drive the browser with video + trace capture |
| Recording | Playwright | Browser video of the run |
| Timeline | Playwright trace | Ground truth for when actions happened |
| Optional script | `docgen per-function-generate` (LLM) | Draft narration lines tied to steps for short clips |
| Assembly | docgen + ffmpeg (as configured) | Fit voice, optional retiming for legibility |

**Contrast:** long-form matches one continuous TTS read to a Manim scene using timing derived from that read. Short clips use Playwright’s capture and trace as the clock for what you see.

---

## Note for models

Segment **05** voice-over describes this **tool chain**, not Python modules, JSON fields, or parsing logic.
