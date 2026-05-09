#!/usr/bin/env bash
#
# TOTAL reset for docs/demos dogfood: full wipe of regenerable assets, then
# regenerate everything via docgen + OpenAI.
#
# Every step here is a portable `docgen` subcommand — an external project
# (e.g. coursebuilder) can reproduce this exact flow simply by installing
# docgen and running the same commands from its own bundle directory. The
# only bundle-specific bit is `_seed-examples.sh` at the very end, which
# copies the dogfood bundle into `<repo>/examples/`; external projects do
# not need it.
#
# Flow:
#   1. Capture the current segment list (stems) from docgen.yaml -> a tmp file.
#      This file is the only thing we carry across the wipe; everything else
#      in the bundle that is regenerable is deleted.
#   2. ``docgen clean-bundle`` (full wipe — no --keep-narration) removes
#      narration/*.md, animations/, audio/*.mp3, terminal/ contents,
#      recordings/*.mp4, recordings/per-function/, per-function/*.docgen.yaml,
#      and docgen.yaml.
#   3. ``docgen init . --defaults --segments-file <tmp>`` rebuilds an empty
#      scaffold for those segments.
#   4. ``docgen yaml-generate`` discovers visual_map entries from disk.
#   5. ``docgen narration-generate --all --force`` fills narration/*.md.
#   6. ``docgen scene-generate --all`` fills animations/scenes.py for every
#      segment that has no VHS tape or capture script.
#   7. ``docgen yaml-generate`` re-syncs visual_map after scenes.py is filled.
#   8. ``docgen generate-all`` produces audio + recordings.
#   9. ``docgen per-function-generate --force`` writes manifests for every
#      raw Playwright spec under repo fixtures/.
#  10. ``docgen per-function-render`` runs `npx playwright test --trace=on
#      --video=on` for every manifest (Playwright handles the dev server),
#      parses trace.zip, syncs narration to real action timestamps, and
#      writes recordings/per-function/<slug>.mp4.
#  11. ``docgen validate --pre-push`` enforces the bundle invariants.
#  12. _seed-examples.sh copies the bundle into `<repo>/examples/` (dogfood-only).
#
# Requires the toolchain that matches what discovery finds on disk:
#   * OPENAI_API_KEY (narration, TTS, optional yaml/scene prose)
#   * Manim + ffmpeg whenever any segment has a `class …Scene` in animations/scenes.py
#   * VHS / ttyd / Xvfb whenever any segment has a matching terminal/<stem>.tape
#   * Node/npm + Playwright Chromium when fixtures contain a Playwright project
#
# Scope: docs/demos only. Preserves: narration/README.md, terminal/README.md,
# ../../fixtures/, scripts/.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

VENV="$REPO_ROOT/.venv"
if [ -f "$VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "[total-reset] ERROR: OPENAI_API_KEY required (narration + scene regeneration)." >&2
  exit 2
fi

SEGMENTS_FILE="$(mktemp -t docgen-segments-XXXXXX.txt)"
trap 'rm -f "$SEGMENTS_FILE"' EXIT

echo "=== [$(date +%H:%M:%S)] capture segment list -> $SEGMENTS_FILE ==="
python3 <<PY
import sys
from pathlib import Path

import yaml

cfg_path = Path("docgen.yaml")
out_path = Path("$SEGMENTS_FILE")

stems: list[str] = []
seen: set[str] = set()

if cfg_path.is_file():
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    seg_ids = raw.get("segments", {}).get("all") or []
    seg_names = raw.get("segment_names") or {}
    if isinstance(seg_ids, list) and isinstance(seg_names, dict):
        for sid in seg_ids:
            name = seg_names.get(sid)
            if isinstance(name, str) and name and name not in seen:
                stems.append(name)
                seen.add(name)

if not stems:
    narr = Path("narration")
    if narr.is_dir():
        for f in sorted(narr.glob("*.md")):
            if f.name.lower() == "readme.md":
                continue
            stem = f.stem
            if stem and stem not in seen:
                stems.append(stem)
                seen.add(stem)

if not stems:
    print("[total-reset] no existing segments found; init will fall back to 01-intro", file=sys.stderr)

out_path.write_text("\n".join(stems) + ("\n" if stems else ""), encoding="utf-8")
print(f"[total-reset] captured {len(stems)} segment(s):")
for s in stems:
    print(f"  - {s}")
PY

echo "=== [$(date +%H:%M:%S)] TOTAL RESET: docgen.yaml + assets (docgen clean-bundle) ==="
docgen --config docgen.yaml clean-bundle -y --reset-catalog --delete-config

echo "=== [$(date +%H:%M:%S)] scaffold docgen.yaml (init --defaults --segments-file) ==="
docgen init . --defaults --segments-file "$SEGMENTS_FILE"

echo "=== [$(date +%H:%M:%S)] yaml-generate (merge defaults + discover visual_map) ==="
docgen --config docgen.yaml yaml-generate

echo "=== [$(date +%H:%M:%S)] narration-generate --all --force ==="
docgen --config docgen.yaml narration-generate --all --force

echo "=== [$(date +%H:%M:%S)] scene-generate --all (skip segments with existing tape/script) ==="
docgen --config docgen.yaml scene-generate --all

echo "=== [$(date +%H:%M:%S)] yaml-generate (re-sync visual_map + manim from scenes.py) ==="
docgen --config docgen.yaml yaml-generate

echo "=== [$(date +%H:%M:%S)] yaml-generate --list-gaps ==="
docgen --config docgen.yaml yaml-generate --list-gaps

echo "=== [$(date +%H:%M:%S)] generate-all ==="
docgen --config docgen.yaml generate-all

echo "=== [$(date +%H:%M:%S)] per-function-generate --force ==="
docgen --config docgen.yaml per-function-generate --force

echo "=== [$(date +%H:%M:%S)] per-function-render ==="
docgen --config docgen.yaml per-function-render

echo "=== [$(date +%H:%M:%S)] validate --pre-push ==="
docgen --config docgen.yaml validate --pre-push

echo "=== [$(date +%H:%M:%S)] seed repo examples/ (dogfood-only) ==="
"$SCRIPT_DIR/_seed-examples.sh"

echo "=== [$(date +%H:%M:%S)] DONE — total reset + regen complete ==="
