# Maintainer hints for docgen

Put **Markdown or plain text** here when you want stable, reviewable steering for OpenAI-backed commands—without pasting long prose into generated artifacts. Paths are **repo-root-relative** (see `repo_root:` in `docgen.yaml`).

## Dogfood: segment 04 only

Segments **01–03** use **only** `README.md` + `AGENTS.md` in the global `narration_from_source` / `manim_scene_generation` context.  
Segment **`04`** (`04-pipeline-hints`) is the **hint-driven section**: add hint paths under:

- `narration_from_source.segments."04".context.paths`
- `manim_scene_generation.segments."04".context.paths`

| File | Role |
|------|------|
| `narration-tts.md` | Rules for spoken scripts (no backticks, plain prose). |
| `manim-scene-specs.md` | Declarative Manim YAML / `_box` row constraints. |
| `segment-04-topic.md` | What segment 04 should explain (hints + two pipeline modes). |

Typical regen for the new segment (from `docs/demos`): `docgen tts --segment 04` → `docgen timestamps` → `docgen scene-spec-generate --segment 04 --compile` → `docgen manim` → `docgen compose` → `docgen concat full-demo`.

**Cursor / editors:** files under `hints/` are intentional inputs (`.cursor/rules/no-asset-edits.mdc` category B). Not produced by `docgen`; not removed by `clean-bundle` unless you delete them.
