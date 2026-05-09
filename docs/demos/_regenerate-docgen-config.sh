#!/usr/bin/env bash
# Run docgen yaml-generate on this bundle (same as any downstream repo).
# Examples: ./_regenerate-docgen-config.sh
#           ./_regenerate-docgen-config.sh --llm
#           ./_regenerate-docgen-config.sh --list-gaps
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.venv/bin/activate"
fi
exec docgen --config docgen.yaml yaml-generate "$@"
