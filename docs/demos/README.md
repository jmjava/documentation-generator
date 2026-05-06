# docgen demo videos (dogfood)

This tree is the **in-repo dogfood** project: the documentation-generator repository eating its own cooking. Configuration lives in `docgen.yaml` (paths relative to this directory unless noted).

## Prerequisites

Full `docgen generate-all` needs **Manim**, **ffmpeg**, **VHS**, **ttyd**, **Xvfb** (or a display) for terminal tapes, **Playwright** only if you re-record browser footage, and **`OPENAI_API_KEY`** for Whisper timestamps, TTS, and optional `narration-generate`.

Segment **07** uses a **checked-in WebM** under `terminal/rendered/`; no Playwright run is required for a basic pipeline pass if you keep that file.

## Commands (typical)

From repository root:

```bash
cd docs/demos
docgen --config docgen.yaml validate --help
```

Source-catalog metadata (repo root; shared with other workflows):

```bash
cd docs/demos
docgen --config docgen.yaml catalog init         # once; creates ../../docgen.catalog.yaml
docgen --config docgen.yaml catalog stale
```

Discovery and catalog merge (Node Playwright projects under the repo root):

```bash
cd docs/demos
docgen --config docgen.yaml discover-tests --merge-catalog
docgen --config docgen.yaml catalog refresh
```

Optional narration draft for segment 07 (requires `OPENAI_API_KEY`):

```bash
cd docs/demos
docgen --config docgen.yaml narration-generate --segment 07 --dry-run
docgen --config docgen.yaml narration-generate --segment 07
```

Full pipeline (heavy):

```bash
cd docs/demos
docgen --config docgen.yaml generate-all
# or iterate with skips, e.g. --skip-tts after audio exists
```

Validation:

```bash
cd docs/demos
docgen --config docgen.yaml validate
docgen --config docgen.yaml validate --pre-push
```

Upstream consumer dogfood (separate clone) is described in `milestones/upstream-dogfood.md` at the repo root.
