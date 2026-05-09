# Narration focus (segment 04 — pipeline hints)

This segment is the **hook** that explains maintainer hint files, not the three overview segments.

Cover in spoken order:

1. **Two demo styles** — long-form **Manim** segments vs short **Playwright** tutorials from real tests.
2. **Hint files** — Markdown under `docs/demos/hints/` is committed input; it steers OpenAI for `scene-spec-generate` and `narration-generate` without editing generated narration or scenes by hand.
3. **This segment** — wired in `docgen.yaml` so **only segment `04`** pulls these hint paths; segments zero-one through zero-three stay on README and AGENTS only.
4. **Declarative Manim** — YAML specs compile to layout-safe scenes; raw `scene-generate` stays for richer motion when you need it.
5. Close with: run `docgen` from the bundle directory and keep hint files in Git next to `docgen.yaml`.

Keep sentences short; bullets here are for the author or LLM — the final `narration/*.md` must stay plain prose (see `narration-tts.md`).
