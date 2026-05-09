---
docgen:
  segment:
    create: true
    id: "05"
    stem: 05-playwright-demos
  wiring:
    visual:
      type: manim
      scene: PlaywrightDemosScene
      source: PlaywrightDemosScene.mp4
    narration:
      system_prompt: |
        You write narration markdown for a technical demo video. The text will be read by text-to-speech.

        Focus on which tools and commands participate in the pipeline and what each step is for.
        Name docgen subcommands, OpenAI text-to-speech, Whisper-style timing via docgen timestamps,
        Manim, ffmpeg composition, Playwright, traces, and optional LLM-assisted narration for short
        clips — at the level a maintainer would explain in a walkthrough, not source-code or
        algorithm internals. Do not dive into response formats, JSON shapes, field names, parsing
        rules, or how functions are implemented.

        Use a few short paragraphs with blank lines; keep total length moderate (clear but not a
        lecture). No backticks, no hash headings, no bullet lists.

        No episode ordinals, no "in this section" meta talk, no YAML front matter, no whole-script
        code fences. Do not lecture the listener about formatting or instructions.
      hints:
      - >-
        Long-form explainer path: narration markdown, docgen text-to-speech producing the segment
        mp3, docgen timestamps using hosted speech-to-text so diagrams can follow the real voice,
        Manim for the visual, docgen compose with ffmpeg to marry picture and sound, validation for
        length drift — describe roles only, not file layouts or APIs.
      - >-
        Short browser-demo path: docgen drives Playwright tests with recording and trace enabled,
        docgen demo-function as the capture entry point, traces as the timing truth for what happened
        in the browser, optional docgen per-function style steps so narration can match actions —
        again name tools and purposes, not parsing or alignment algorithms.
      - >-
        One crisp contrast: long pieces align one continuous voice track to a Manim render using
        timing from that track; short clips lean on Playwright’s own recording and trace timeline
        instead of re-analyzing one big narration file.
      - >-
        Optional one-liner that busy clips can be slowed for viewing legibility; do not explain ffmpeg
        filters or math.
      context:
        paths:
        - docs/demos/hints/narration-tts.md
        - docs/demos/hints/segment-05-topic.md
        - docs/demos/hints/playwright-demo-code.md
    manim_scene:
      hints:
      - >-
        Diagram lists tools in order for long-form versus short-form with short labels only —
        TTS, timestamps plus Whisper, Manim, compose, then Playwright, trace, and demo-function —
        no module-level detail.
      context:
        paths:
        - docs/demos/hints/manim-scene-specs.md
        - docs/demos/hints/segment-05-topic.md
        - docs/demos/hints/playwright-demo-code.md
---

# Segment 05 — editorial notes (not read aloud)

## Must appear in generated narration (checklist)

1. **Tools off the shelf:** docgen, OpenAI TTS, docgen timestamps (Whisper-backed), Manim, ffmpeg compose, Playwright, trace, optional LLM-assisted narration for shorts.
2. **Long-form:** one voice track + timed diagram + mux — purpose of each step, not internals.
3. **Short-form:** browser capture + trace-backed timing vs long-form — purpose-level contrast only.
4. **Avoid:** API parameters, JSON shapes, module or function names beyond docgen subcommands, parsing rules.

## TTS hygiene

- Final `narration/05-playwright-demos.md`: plain prose per `narration-tts.md` (no backticks, headings, bullets in output).
