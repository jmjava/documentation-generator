#!/usr/bin/env bash
# Rebuild everything after new audio: Manim → VHS → compose → validate → concat.
# Wraps: docgen rebuild-after-audio
set -euo pipefail
DEMOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Rebuild after audio (skipping TTS, using existing audio/*.mp3)"
exec docgen --config "$DEMOS_DIR/docgen.yaml" rebuild-after-audio
