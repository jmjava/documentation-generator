# Milestone 1 — Production Hardening

**Goal:** Make docgen reliable enough to merge into `tekton-dag` and use in real CI.

## Items

- [ ] **Install tesseract in CI** — add `apt-get install tesseract-ocr` to `ci.yml` so OCR validation runs on every push (catches "command not found", `.venv` stacking, etc. in terminal recordings)
- [ ] **Install ffmpeg in CI** — add `apt-get install ffmpeg` so compose-guard and integration tests run instead of being skipped
- [ ] **Tighten Manim animation pacing** — add more animation beats to `DocgenOverviewScene` and `WizardGUIScene` so static holds drop from ~57% to <30% of the video
- [ ] **Merge `milestone/doc-generator` into `tekton-dag` main** — integrate `docgen.yaml`, wrapper scripts, and the 14-segment demo pipeline into the parent repo
- [ ] **End-to-end smoke test** — add a CI job that runs `docgen generate-all --dry-run` to verify the full pipeline config is valid without calling OpenAI or rendering video
