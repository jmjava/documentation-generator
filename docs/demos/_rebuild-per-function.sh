#!/usr/bin/env bash
#
# Thin wrapper around `docgen per-function-render` for the dogfood bundle.
# All real logic — Playwright spec discovery, dev-server lifecycle (via the
# project's own playwright.config.ts webServer block), trace-based narration
# sync — lives inside the docgen package, so any project can reproduce this
# step with `docgen per-function-render` (no scripts to copy).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/../../.venv"
if [ -f "$VENV/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

ENV_FILE="$SCRIPT_DIR/../../.env"
if [ -f "$ENV_FILE" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

exec docgen --config docgen.yaml per-function-render "$@"
