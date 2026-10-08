#!/usr/bin/env bash
# Proving test: a baselined finding passes; a new finding fails. CI must not rewrite the baseline.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHECK="${SCRIPT_DIR}/check-vulture.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OK="$TMP/ok.py"
BAD="$TMP/bad.py"
BASELINE="$TMP/baseline.txt"
printf 'def keep(known_dead):\n    return 1\n' > "$OK"
printf "1 %s unused variable 'known_dead'\n" "$OK" > "$BASELINE"
if ! python3 "$CHECK" --baseline "$BASELINE" "$OK"; then
  echo "expected PASS for a baselined unused variable" >&2
  exit 1
fi

printf 'def keep(known_dead):\n    return 1\ndef again(known_dead):\n    return 2\n' > "$OK"
if python3 "$CHECK" --baseline "$BASELINE" "$OK"; then
  echo "expected FAIL when a baselined finding's count rises" >&2
  exit 1
fi

printf 'def keep(known_dead):\n    return 1\n' > "$OK"
printf 'def other(new_dead):\n    return 1\n' > "$BAD"
if python3 "$CHECK" --baseline "$BASELINE" "$OK" "$BAD"; then
  echo "expected FAIL for a finding that is not in the baseline" >&2
  exit 1
fi

if grep -n 'make-whitelist' "$ROOT/.github/workflows/ci.yml"; then
  echo "CI must not rewrite the vulture baseline" >&2
  exit 1
fi
if ! grep -q 'scripts/check-vulture.py' "$ROOT/.github/workflows/ci.yml"; then
  echo "CI does not run check-vulture.py" >&2
  exit 1
fi
echo "test-check-vulture: PASS"
