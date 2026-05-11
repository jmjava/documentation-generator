# Maintainer hints for docgen

Put **Markdown** here for stable, reviewable steering for OpenAI-backed commands. Paths in front matter are **repo-root-relative** (see `repo_root:` in `docgen.yaml`).

## New segments: one source of truth (`yaml-generate`)

**Do not hand-edit** `docs/demos/docgen.yaml` for segment ids, `segment_names`, `visual_map`, or per-segment `narration_from_source` / `manim_scene_generation` blocks for bundles that use this pattern. Put everything in **YAML front matter** at the top of a `hints/segment-NN-topic.md` file (skip `README.md`), then run:

```bash
docgen --config docgen.yaml yaml-generate
```

That merges into `docgen.yaml`: `segments.*`, `segment_names`, disk-based `visual_map` discovery, **then** your **`docgen.wiring`** overrides and narration/manim extras.

### Front matter: `docgen.segment`

Adds the id to `segments.all` / `default` and sets `segment_names`:

```yaml
---
docgen:
  segment:
    create: true
    id: "05"
    stem: 05-my-topic
---
```

The first `segment` declaration per id wins (files sorted by path). Disable all hint merging with `discovery.merge_hint_segments: false` or `docgen yaml-generate --no-merge-hint-segments`.

### Front matter: `docgen.wiring` (same file)

After discovery, **`yaml-generate`** applies:

- **`wiring.visual`** → `visual_map["NN"]` (e.g. `type` / `scene` / `source` for Manim)
- **`wiring.narration`** → `narration_from_source.segments["NN"]` (`hints`, `context.paths`, …)
- **`wiring.manim_scene`** → merged into `manim_scene_generation.segments["NN"]` (adds `hints` / `context.paths` on top of synced `class_name`)

See **`segment-04-topic.md`** and **`segment-05-topic.md`** in this directory for full examples.

## Dogfood segments 04–05

| File | Role |
|------|------|
| `narration-tts.md` | Rules for spoken scripts (no backticks, plain prose). |
| `manim-scene-specs.md` | Declarative Manim YAML / `_box` / pages. |
| `compose-pipeline.md` | Technical notes for segment 05 (TTS → Manim → compose → validate). |
| `segment-04-topic.md` | Segment 04 — pipeline hints; includes `segment` + `wiring`. |
| `segment-05-topic.md` | Segment 05 — compose and validate pipeline; includes `segment` + `wiring`. |

After changing hints: **`yaml-generate`** → TTS / timestamps / scene-spec / manim / compose / concat as usual.

**Cursor / editors:** `hints/**` are intentional inputs (`.cursor/rules/no-asset-edits.mdc` category B). Not produced by `docgen`; not removed by `clean-bundle` unless you delete them.
