# Compose pipeline (segment 05 — technical notes, not read aloud)

Docgen turns narration plus visuals into finished MP4s using a **single** stack today:

| Step | Role |
|------|------|
| Narration | Markdown under `narration/` — plain prose for TTS |
| TTS | `docgen tts` — segment audio |
| Timestamps | `docgen timestamps` — Whisper-style alignment → `animations/timing.json` |
| Manim | `docgen manim` — diagrams from `animations/scenes.py` (declarative specs under `animations/specs/`) |
| Compose | `docgen compose` — mux audio + video with ffmpeg |
| Validate | `docgen validate` / `validate --pre-push` — drift and narration lint |
| Concat | `docgen concat full-demo` — optional joined reel |

**Contrast (conceptual):** long-form pieces pair **one** continuous voice track with a Manim scene; timing comes from that same track. There is no separate browser-capture or trace timeline in the supported CLI (historic Playwright/demo-function paths were removed).
