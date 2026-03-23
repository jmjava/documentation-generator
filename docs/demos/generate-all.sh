#!/usr/bin/env bash
# Full pipeline: TTS → Manim → VHS → compose → validate → concat.
# Wraps: docgen generate-all
set -euo pipefail
DEMOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        exec docgen --config "$DEMOS_DIR/docgen.yaml" tts --dry-run
    fi
    ARGS+=("$arg")
done
exec docgen --config "$DEMOS_DIR/docgen.yaml" generate-all "${ARGS[@]}"
