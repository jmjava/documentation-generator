# Narration style for TTS (dogfood)

When drafting **`narration/*.md`** for `docgen tts` / validate:

- **Plain spoken prose** — avoid markdown headings, bullets, and **inline backticks** (narration_lint rejects `` `code` ``).
- Prefer phrasing like: run docgen init, open the docgen.yaml file — not fenced or backtick-wrapped command names.
- Keep sentences short enough for calm TTS; expand acronyms on first use if needed.
