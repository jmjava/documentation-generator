#!/usr/bin/env bash
# Proving test: a higher survived count fails. The checker does not rewrite the baseline.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHECK="${SCRIPT_DIR}/check-mutation-score.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BASELINE="$TMP/baseline.json"
STATS="$TMP/stats.json"
printf '%s\n' '{"module":"fixture","survived":2,"total":10}' > "$BASELINE"
printf '%s\n' '{"survived":2,"total":10,"check_was_interrupted_by_user":0}' > "$STATS"
before="$(cksum "$BASELINE")"
if ! python3 "$CHECK" --baseline "$BASELINE" --stats "$STATS"; then
  echo "expected PASS when survived stays at the ceiling" >&2
  exit 1
fi
after="$(cksum "$BASELINE")"
if [ "$before" != "$after" ]; then
  echo "checker rewrote the baseline" >&2
  exit 1
fi

printf '%s\n' '{"survived":3,"total":11,"check_was_interrupted_by_user":0}' > "$STATS"
if python3 "$CHECK" --baseline "$BASELINE" --stats "$STATS"; then
  echo "expected FAIL when survived rises" >&2
  exit 1
fi

if grep -n 'mutation-path-filters-baseline.json' "$ROOT/.github/workflows/ci.yml"; then
  echo "CI must not rewrite the mutation baseline" >&2
  exit 1
fi
echo "test-check-mutation: PASS"
