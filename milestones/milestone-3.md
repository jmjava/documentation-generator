# Milestone 3 — Multi-Language Narration

**Goal:** Generate demo videos in multiple languages from a single English narration source.

## Target Languages (initial)

- Chinese (Mandarin, `zh`)
- Spanish (`es`)
- Japanese (`ja`)
- Additional languages easy to add via config

## Items

- [ ] **Translation stage** — `docgen translate --lang zh` calls an LLM (GPT-4o) to translate narration Markdown files, preserving technical terms and TTS-friendly phrasing
- [ ] **Per-language TTS voices** — configure voice per language in `docgen.yaml` under `tts.voices.zh`, `tts.voices.es`, etc. OpenAI TTS supports Chinese, Spanish, Japanese natively
- [ ] **Language-aware pipeline** — `docgen generate-all --lang zh` runs TTS → timestamps → compose for the target language, reusing the same visual assets (Manim/VHS/slides are language-neutral)
- [ ] **Output structure** — recordings land in `recordings/zh/`, `recordings/es/` etc., with per-language concat and Pages index
- [ ] **GitHub Pages language switcher** — add a language dropdown to `index.html` that swaps video sources
- [ ] **Cost estimation** — `docgen translate --dry-run` shows estimated token count and cost before calling the API (GPT-4o translation is ~$2.50/1M input tokens — a 6-segment demo with ~3K words is well under $0.01 per language)
- [ ] **Translation review workflow** — `docgen wizard` supports editing translated narration with side-by-side English reference
- [ ] **Validation** — `docgen validate` checks translated narrations for length parity with English (±20%) to catch truncated or bloated translations

## Cost Notes

OpenAI TTS pricing is the same regardless of language. The main additional cost is the translation step via GPT-4o, which is negligible for typical demo narration (~2–5K words). Chinese (Mandarin) is well-supported by both GPT-4o for translation and OpenAI TTS for speech synthesis.
