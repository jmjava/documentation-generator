# Maintainer hints for docgen

Put **Markdown or plain text** here when you want stable, reviewable steering for OpenAI-backed commands—without pasting long prose into generated artifacts.

**Wire paths in `docgen.yaml`**, for example under:

- `narration_from_source.context.paths` — e.g. `hints/overview-topic.md`
- `manim_scene_generation.context.paths` — same idea for `scene-spec-generate` / `scene-generate`

Then run `docgen narration-generate`, `docgen scene-spec-generate`, etc. as usual.

**Cursor / editors:** creating and editing files under `hints/` is intentional input (see `.cursor/rules/no-asset-edits.mdc` category B). This directory is **not** produced by `docgen`; it is not deleted by `clean-bundle` unless you remove it yourself.
