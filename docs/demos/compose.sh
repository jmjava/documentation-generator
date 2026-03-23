#!/usr/bin/env bash
# Compose segments (audio + video via ffmpeg).
# Wraps: docgen compose
set -euo pipefail
DEMOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec docgen --config "$DEMOS_DIR/docgen.yaml" compose "$@"
