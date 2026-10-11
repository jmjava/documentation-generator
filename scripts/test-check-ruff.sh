#!/usr/bin/env bash
# Proving test: a baselined finding passes; a new finding fails. CI must not rewrite the baseline.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHECK="${SCRIPT_DIR}/check-ruff.py"
BASELINE_FILE="${ROOT}/config/ruff-baseline.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OK="$TMP/ok.py"
BAD="$TMP/bad.py"
BASELINE="$TMP/baseline.txt"
printf 'import os\n' > "$OK"

printf '# empty ceiling\n' > "$BASELINE"
if python3 "$CHECK" --baseline "$BASELINE" "$OK"; then
  echo "expected FAIL for a finding against an empty baseline" >&2
  exit 1
fi

printf '1 %s F401 `os` imported but unused\n' "$OK" > "$BASELINE"
if ! python3 "$CHECK" --baseline "$BASELINE" "$OK"; then
  echo "expected PASS for a baselined unused import" >&2
  exit 1
fi

printf 'import os\ndef a():\n    import os\n    return 1\n' > "$OK"
printf '1 %s F401 `os` imported but unused\n' "$OK" > "$BASELINE"
printf '1 %s F811 Redefinition of unused `os` from line 1: `os` redefined here\n' "$OK" >> "$BASELINE"
if python3 "$CHECK" --baseline "$BASELINE" "$OK"; then
  echo "expected FAIL when a baselined finding's count rises" >&2
  exit 1
fi

printf 'import os\n' > "$OK"
printf 'import sys\n' > "$BAD"
printf '1 %s F401 `os` imported but unused\n' "$OK" > "$BASELINE"
if python3 "$CHECK" --baseline "$BASELINE" "$OK" "$BAD"; then
  echo "expected FAIL for a finding that is not in the baseline" >&2
  exit 1
fi

if grep -q 'config/ruff-baseline.txt' "$ROOT/.github/workflows/ci.yml"; then
  echo "CI must not rewrite the ruff baseline" >&2
  exit 1
fi
if ! grep -q 'scripts/check-ruff.py' "$ROOT/.github/workflows/ci.yml"; then
  echo "CI does not run check-ruff.py" >&2
  exit 1
fi
if grep -E 'write_text|open\([^)]*["'\'']w' "$CHECK" >/dev/null; then
  echo "check-ruff.py must not write the baseline" >&2
  exit 1
fi

before="$(sha256sum "$BASELINE_FILE")"
python3 "$CHECK" src tests
after="$(sha256sum "$BASELINE_FILE")"
if [[ "$before" != "$after" ]]; then
  echo "check-ruff.py rewrote the committed baseline" >&2
  exit 1
fi
echo "test-check-ruff: PASS"
