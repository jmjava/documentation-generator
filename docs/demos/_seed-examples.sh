#!/usr/bin/env bash
# Historic dogfood step: copied per-function manifests into <repo>/examples/.
# That pipeline was removed; keep a no-op so total-reset scripts can still call this hook.
set -euo pipefail
echo "[seed-examples] skipped (no per-function manifests to sync — see AGENTS.md)"
exit 0
