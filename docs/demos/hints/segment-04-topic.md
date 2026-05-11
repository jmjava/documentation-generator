---
docgen:
  segment:
    create: true
    id: "04"
    stem: 04-pipeline-hints
  wiring:
    visual:
      type: manim
      scene: PipelineHintsScene
      source: PipelineHintsScene.mp4
    narration:
      hints:
      - This segment explains maintainer hint files under docs/demos/hints and how yaml-generate merges them into docgen.yaml.
      context:
        paths:
        - docs/demos/hints/narration-tts.md
        - docs/demos/hints/segment-04-topic.md
    manim_scene:
      hints:
      - Boxes for Hint files, Declarative YAML, Manim long-form walkthroughs; tie labels to segment-04-topic.
      context:
        paths:
        - docs/demos/hints/manim-scene-specs.md
        - docs/demos/hints/segment-04-topic.md
---

# Narration focus (segment 04 — pipeline hints)

This segment is the **hook** that explains maintainer hint files, not the three overview segments.

Cover in spoken order:

1. **Primary style** — long-form **Manim** segments paired with scripted narration (no separate browser-capture stack).
2. **Hint files** — Markdown under `docs/demos/hints/` is committed input; it steers OpenAI for `scene-spec-generate` and `narration-generate`, and **segment wiring** is merged by **`docgen yaml-generate`** from front matter (`docgen.segment` and `docgen.wiring`) — not by hand-editing `docgen.yaml` in an editor.
3. **Declarative Manim** — YAML specs compile to layout-safe scenes; custom motion belongs in hand-maintained Python outside generated marker blocks.
4. Close with: run **`docgen yaml-generate`** after changing hints, then run `docgen` TTS and visual steps from the bundle directory.

Keep sentences short; bullets here are for the author or LLM — the final `narration/*.md` must stay plain prose (see `narration-tts.md`).
