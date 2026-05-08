# `milestones/demo-smoke/` — one-off proof-of-work artifacts

This directory holds the **input fixtures** that proved the per-action
`demo-function` pipeline (Chromium → captured timeline → slowdown →
per-action TTS → padded mux) works end-to-end against a static page.

## Tracked in git

- [`lesson.docgen.yaml`](lesson.docgen.yaml) — manifest with `actions[*].say`
  + `output_budget.playback_speed_factor: 0.7`.
- [`demo-page.html`](demo-page.html) — tiny static page Playwright drives via
  `file://`. No server needed.

## NOT tracked (regenerated, not committed)

The rendered MP4, poster PNG, frame strip, and `manifest.json` snapshot are
binary artifacts — `.gitignore` excludes `*.mp4`, `*.png`, `*.manifest.json`
under this directory. They are reproducible at any time via the canonical
**e2e test** in `tests/e2e/test_demo_function_e2e.py` (which is the
authoritative version of this scenario, runs in CI, and asserts invariants).

## Reproducing locally

```bash
export OPENAI_API_KEY=sk-...
docgen demo-function \
  --manifest milestones/demo-smoke/lesson.docgen.yaml \
  --output-dir /tmp/demo-smoke/out

# Or via the e2e test (skips cleanly without a key):
pytest tests/e2e/test_demo_function_e2e.py -v
```

The e2e test is the source of truth; this directory exists for ad-hoc
visual review only. New manifest fields go into the e2e fixture
(`tests/e2e/demo-function/`) and the docs (`docs/demo-function.md`) — not
here.
