---
docgen:
  segment:
    create: true
    id: "05"
    stem: 05-compose-pipeline
  wiring:
    visual:
      type: manim
      scene: ComposePipelineScene
      source: ComposePipelineScene.mp4
    narration:
      system_prompt: |
        You write narration markdown for a technical demo video. The text will be read by text-to-speech.

        Focus on which docgen commands and external tools participate in the pipeline and what each step is for.
        Cover OpenAI text-to-speech, Whisper-style timing via docgen timestamps, Manim for visuals,
        ffmpeg composition, validation, and optional concat — at the level a maintainer would explain in a
        walkthrough, not source-code or algorithm internals.

        Use a few short paragraphs with blank lines; keep total length moderate (clear but not a
        lecture). No backticks, no hash headings, no bullet lists.

        No episode ordinals, no "in this section" meta talk, no YAML front matter, no whole-script
        code fences. Do not lecture the listener about formatting or instructions.
      hints:
      - >-
        Walk the long-form path only: narration markdown, docgen TTS, docgen timestamps so diagrams
        track the real voice, Manim for the visual, docgen compose with ffmpeg, then validate and
        optional concat — describe roles only, not file layouts or APIs.
      - >-
        One crisp idea: everything hangs off one voice track and timed Manim; there is no separate
        browser automation layer in the supported tool.
      - >-
        Optional one-liner that busy clips can be slowed for viewing legibility; do not explain ffmpeg filters or math.
      context:
        paths:
        - docs/demos/hints/narration-tts.md
        - docs/demos/hints/segment-05-topic.md
        - docs/demos/hints/compose-pipeline.md
    manim_scene:
      hints:
      - >-
        Diagram lists tools in order with short labels — TTS, timestamps plus Whisper, Manim, compose,
        validate, concat — no module-level detail.
      context:
        paths:
        - docs/demos/hints/manim-scene-specs.md
        - docs/demos/hints/segment-05-topic.md
        - docs/demos/hints/compose-pipeline.md
---

# Segment 05 — editorial notes (not read aloud)

## Must appear in generated narration (checklist)

1. **Tools:** docgen, OpenAI TTS, docgen timestamps (Whisper-backed), Manim, ffmpeg compose, validate, concat.
2. **Flow:** one voice track, timed diagram, mux, checks — purpose of each step, not internals.
3. **Avoid:** Playwright, browser traces, demo-function, per-function, or any removed CLI surface.

## TTS hygiene

- Final `narration/05-compose-pipeline.md`: plain prose per `narration-tts.md` (no backticks, headings, bullets in output).
