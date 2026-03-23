#!/usr/bin/env bash
# Validate recordings: stream presence, A/V drift, narration lint.
# Wraps: docgen validate --pre-push
set -euo pipefail
DEMOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec docgen --config "$DEMOS_DIR/docgen.yaml" validate --pre-push
