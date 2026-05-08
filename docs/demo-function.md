# `docgen demo-function` — per-function video docs reference

`docgen demo-function` renders **one short, single-purpose MP4 per
function** — the docs-site analogue of one Playwright `test('…')`
describing one behavior. It is the per-function counterpart to the
long-form `docgen generate-all` pipeline that produces the multi-segment
demos under `docs/demos/`.

This page is the schema + behavior reference. For the high-level pitch
see the [README](../README.md#per-function-video-docs-docgen-demo-function);
for canonical end-to-end coverage see
[`tests/e2e/test_demo_function_e2e.py`](../tests/e2e/test_demo_function_e2e.py).

## Table of contents

- [Pipeline overview](#pipeline-overview)
- [Manifest schema](#manifest-schema)
- [Per-action narration sync (`say`)](#per-action-narration-sync-say)
- [Slowdown (`playback_speed_factor`)](#slowdown-playback_speed_factor)
- [Captured timeline shape](#captured-timeline-shape)
- [Action kinds](#action-kinds)
- [Output artifacts](#output-artifacts)
- [Caching](#caching)
- [Fail modes & exit codes](#fail-modes--exit-codes)
- [CLI reference](#cli-reference)

## Pipeline overview

```
manifest (YAML / @pytest.mark.docgen)
    │
    ▼
Playwright Chromium  ──── records visual.webm + timeline.json
    │                     (one entry per action: kind, say,
    │                      t_start_ms, t_end_ms — relative to
    │                      the recording's t=0)
    ▼
ffmpeg -filter:v setpts=…  (retime by playback_speed_factor)
    │
    ▼
ffmpeg subtitles=…vtt    (burn timed `say` cues — scaled times)
    │
    ▼
OpenAI gpt-4o-mini-tts   (one MP3 per action.say,
    │                     placed at t_action / speed_factor;
    │                     overlapping clips are pushed past the
    │                     predecessor's tail so they never mix)
    ▼
ffmpeg adelay+amix+apad  (compose narration to exact video length)
    │
    ▼
ffmpeg padded mux         (audio padded with silence so video
    │                     length wins — never `-shortest`)
    ▼
rendered.mp4 + poster.png + manifest.json + fragment.txt + cache-status.txt
```

## Manifest schema

Two equivalent shapes — pick whichever the function lives next to.

### YAML sidecar (`*.docgen.yaml`)

```yaml
identifier: "owner/repo/src/path.ts:functionName"   # required, slugified for fragment_id
intent: "One-sentence description spoken if no `say` is set." # required
setup:
  fixtures:                                          # optional list of files staged
    - tests/fixtures/sample.md                       # into the render work-dir
demonstration:
  kind: playwright                                   # or `cli` (VHS-driven)
  url: "http://127.0.0.1:3000/path"                  # required when kind=playwright + actions
  actions:                                           # see "Action kinds" below
    - kind: click
      selector: '[data-testid="compile"]'
      say: "Clicking compile runs the generator."   # optional per-action narration
output_budget:
  duration_seconds: 30                               # required — recorded-timeline cap
  resolution: "1280x720"                             # WxH, default 1280x720
  playback_speed_factor: 0.7                         # optional, default 1.0; range [0.25, 4.0]
assertions_to_surface:                               # optional fallback caption text
  - "result.status === 'compiled'"                   # only used when no action has `say`
```

Full example: [`examples/lesson_compile.docgen.yaml`](../examples/lesson_compile.docgen.yaml).

### Python `@pytest.mark.docgen(...)`

The marker is read **statically via `ast`** — never imported or `exec`'d.
Keyword args mirror the YAML keys exactly. See
[`examples/sample_test.py`](../examples/sample_test.py).

### TypeScript Playwright spec sidecar

For a `*.spec.ts`, drop a sibling `<spec>.docgen.yaml`. The renderer
records via `npx playwright test --grep "<title>"` instead of driving
declarative actions. See the
[`tests/e2e/`](../tests/e2e/) entries that exercise this path.

## Per-action narration sync (`say`)

Adding a `say:` string to any action turns on **per-action narration
mode**:

- `_drive_playwright` wraps each action in `time.monotonic()` and writes a
  `timeline.json` of `{kind, say, t_start_ms, t_end_ms}` entries against
  the recorded video clock.
- Each `say` is sent to OpenAI `gpt-4o-mini-tts` (voice `coral`,
  one-sentence narration).
- Audio clips are placed at `(t_start_ms / 1000) / playback_speed_factor`
  in the slowed timeline; a clip whose desired start would land before
  the previous clip finishes is pushed forward (with 0.1s breathing room)
  so two close-together actions never overlap audibly.
- A WebVTT track is built from the same scaled timestamps and burned in
  as captions; cues are capped at the next captioned action's start so
  there is no caption stacking.

If **no** action has `say`, the renderer falls back to single-clip mode:
one TTS clip from `intent` plays over the whole video, and
`assertions_to_surface` strings are spread evenly across the timeline as
captions.

`actions[*].say` participates in the cache key (via the actions array
hash), so editing narration text invalidates the cache.

## Slowdown (`playback_speed_factor`)

`output_budget.playback_speed_factor` (default `1.0`, range `[0.25, 4.0]`)
retimes the captured visual via ffmpeg `setpts=1/factor*PTS`:

| Factor | Behavior | Use when |
|---|---|---|
| `1.0` | passthrough | the recording is already legible |
| `0.7` | ~1.43× longer (sweet spot) | clicks feel rushed; a TTS clip needs room to breathe |
| `0.5` | 2× longer | viewers need to read a complex form mid-action |
| `1.5` | ~0.67× shorter | the recording has long uneventful gaps |

Audio is **not** re-pitched — narration clips remain at natural pace and
are placed at scaled timestamps.

`output_budget.duration_seconds` is interpreted against the **recorded**
timeline, not the slowed playback. With `duration_seconds: 25` and
`playback_speed_factor: 0.7`, the trim cap effectively becomes
`25 / 0.7 ≈ 35.7s` of slowed clip, so slowed videos are never chopped in
half.

## Captured timeline shape

Written to `manifest.json`'s `timeline` field on every Playwright run:

```json
{
  "timeline": [
    {
      "kind": "click",
      "say": "We focus the topic input.",
      "t_start_ms": 531,
      "t_end_ms": 578
    },
    {
      "kind": "type",
      "say": "And type a lesson topic — async iterators in this case.",
      "t_start_ms": 578,
      "t_end_ms": 1896
    }
  ]
}
```

Times are wall-clock milliseconds against `time.monotonic()` at the
moment the Playwright action loop began (just before `page.goto`). They
are **not** scaled by `playback_speed_factor` — consumers that want
playback-aligned times divide by `playback_speed_factor`.

`t_end_ms - t_start_ms` is the duration of the action call (e.g. how long
`page.click()` took). For zero-duration actions (e.g. `wait_for` against
an already-present element) the value will be a few milliseconds.

## Action kinds

| Kind | Required params | Optional params | Notes |
|---|---|---|---|
| `goto` | `url` | — | navigate; uses `wait_until="networkidle"` |
| `click` | `selector` | — | |
| `fill` | `selector`, `value` | — | sets value directly |
| `type` | `selector`, `value` | `delay_ms` (default 40) | clicks then keyboard-types char-by-char |
| `wait_for` | `selector` | `timeout_ms` (default 10000) | wait for element to attach |
| `wait_for_text` | `selector`, `text` | `timeout_ms` (default 10000) | wait for visible text match |
| `wait` | `ms` | — | hard wait, no DOM dependency |
| `screenshot` | `path` | — | writes PNG; rarely needed |

All action kinds accept `say` as an optional field for per-action
narration; see [Per-action narration sync](#per-action-narration-sync-say).

## Output artifacts

Five files in `--output-dir`:

| File | Purpose |
|---|---|
| `rendered.mp4` | real ISO MP4 (h264 + aac), captioned + narrated |
| `poster.png` | last frame, suitable for `<video poster=…>` |
| `fragment.txt` | `fn-<slug>` derived from `identifier` (no trailing newline) |
| `manifest.json` | snapshot: identifier, intent, fragment_id, cache_key, duration_seconds, resolution, playback_speed_factor, assertions_to_surface, actions, **timeline**, narration |
| `cache-status.txt` | `hit\n` or `miss\n` |

The snapshot is the source of truth for downstream consumers (the
infrastructure aggregator at `courseforge.github.io` reads it to decide
how to render the per-function card).

## Caching

When `--cache-dir` is provided, the renderer keys on
`sha256(fn_source_sha + intent_sha + fixture_sha + speed=<factor>)` and
reuses the previous output bytes when the key matches. The cache key
naturally invalidates when:

- The function's source file (`.ts` / `.py` / `.tape` / YAML) changes.
- `intent` changes.
- Any staged `fixtures` file changes.
- `playback_speed_factor` changes.
- Any `actions[*]` field changes (including `say`, since the YAML hash
  changes).

A cache hit writes `cache-status.txt: hit\n` and skips the entire render
pipeline (Playwright launch, TTS calls, ffmpeg passes).

## Fail modes & exit codes

The renderer **never** ships silent or partial demos masquerading as
success. The default is fail-loud.

| Code | Constant | Trigger |
|------|----------|---------|
| `0` | `EXIT_OK` | success — `rendered.mp4` exists with both video and audio streams (or `--no-narration` was set) |
| `1` | `EXIT_INVALID` | invalid manifest, render failure, or transient OpenAI network error |
| `2` | `EXIT_TOOLING_MISSING` | missing `ffmpeg` / `playwright` / Chromium / **OPENAI_API_KEY** (or key rejected by OpenAI with `401` / `403`) |
| `78` | `EXIT_NEUTRAL_SKIP` | placeholder manifest (`kind: playwright` with no `url`) — useful in CI |

### Behavior matrix

| Condition | Exit | Output dir |
|---|---|---|
| `OPENAI_API_KEY` unset, no `--no-narration` | `2` | not created |
| `OPENAI_API_KEY` rejected by OpenAI (401/403) | `2` | not created |
| Transient network error during TTS | `1` | partial — clean up and retry |
| `--no-narration` (explicit silent opt-in) | `0` | full artifacts; `narration: null` in snapshot |
| Working key + connectivity | `0` | full artifacts including audio |

The fail-loud behavior is enforced at the **top of `render()`** before
any Chromium launch or ffmpeg pass — so a missing key fails in
milliseconds, not after a 10s capture.

## CLI reference

```bash
docgen demo-function \
  --manifest <PATH | path.py::test_name | spec.ts | spec.ts::title> \
  --output-dir <DIR> \
  [--cache-dir <DIR>] \
  [--grep <SUBSTRING>]              # for kind=playwright spec recordings
  [--no-narration]                  # explicit silent opt-in
```

`--manifest` accepts:

- `*.docgen.yaml` — direct YAML manifest.
- `path/to/test.py::test_function` — Python `@pytest.mark.docgen` marker.
- `spec.ts` — Playwright TypeScript spec (sidecar `<spec>.docgen.yaml` or
  inline `JSON.stringify(...)` annotation; `--grep` selects a single
  test).
- `spec.ts::Test title` — same as `spec.ts --grep "Test title"`.
