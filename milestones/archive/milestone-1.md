# Milestone 1 — Production Hardening

**Goal:** Make docgen reliable enough to merge into `tekton-dag` and use in real CI.

## Items

- [x] **Install tesseract in CI** — `apt-get install tesseract-ocr` added to `ci.yml` unit job
- [x] **Install ffmpeg in CI** — `apt-get install ffmpeg` added to `ci.yml` unit job
- [x] **Tighten Manim animation pacing** — added tagline, sequential outputs, validation checks, config entries, exclude-pattern filter animations; static holds dropped from ~57% to <1%
- [x] **Merge `milestone/doc-generator` into `tekton-dag` main** — fast-forward merged (6 commits, 67 files)
- [x] **End-to-end smoke test** — added `smoke` CI job: config validation, narration lint, TTS dry-run
- [x] **LFS auto-push** — added `git-lfs-push` pre-commit hook; validator skips LFS pointer files gracefully
