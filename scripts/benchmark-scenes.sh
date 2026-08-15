#!/usr/bin/env bash
# Score the standard scene-timing corpus (no bundle, no Manim, no OpenAI).
# Usage:
#   ./scripts/benchmark-scenes.sh
#   ./scripts/benchmark-scenes.sh --format json
#   ./scripts/benchmark-scenes.sh --update-baseline   # after an intentional improvement
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "${root}/.venv/bin/docgen" ]]; then
  exec "${root}/.venv/bin/docgen" benchmark "$@"
fi
exec docgen benchmark "$@"
