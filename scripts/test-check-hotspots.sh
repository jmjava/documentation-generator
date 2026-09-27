#!/usr/bin/env bash
# Proving test: a quiet complex file passes; a frequent complex file fails.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHECK="${SCRIPT_DIR}/check-hotspots.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

commit() {
  git -C "$TMP" -c user.email="sa@example.test" -c user.name="SA" -c commit.gpgsign=false commit -qm "$1"
}

git -C "$TMP" init -q
complex() {
  cat <<'PY'
def branchy(x):
    if x == 1: return 1
    if x == 2: return 2
    if x == 3: return 3
    if x == 4: return 4
    if x == 5: return 5
    if x == 6: return 6
    if x == 7: return 7
    if x == 8: return 8
    if x == 9: return 9
    if x == 10: return 10
    if x == 11: return 11
    return 0
PY
}
complex > "$TMP/hot_complex.py"
printf 'def simple(x):\n    return x + 1\n' > "$TMP/hot_simple.py"
complex > "$TMP/quiet_complex.py"
git -C "$TMP" add hot_complex.py hot_simple.py quiet_complex.py
commit base
for n in 2 3 4; do
  printf '\n# touch %s\n' "$n" >> "$TMP/hot_complex.py"
  printf '\n# touch %s\n' "$n" >> "$TMP/hot_simple.py"
  git -C "$TMP" add hot_complex.py hot_simple.py
  commit "touch $n"
done

printf '\n# quiet edit\n' >> "$TMP/quiet_complex.py"
git -C "$TMP" add quiet_complex.py
commit "quiet edit"
if ! python3 "$CHECK" --repo "$TMP" --base HEAD~1 --top 2 --paths .; then
  echo "expected PASS for a quiet complex file" >&2
  exit 1
fi

printf '\n# simple edit\n' >> "$TMP/hot_simple.py"
git -C "$TMP" add hot_simple.py
commit "simple edit"
if ! python3 "$CHECK" --repo "$TMP" --base HEAD~1 --top 2 --paths .; then
  echo "expected PASS for a frequent file that is not complex" >&2
  exit 1
fi

printf '\n# hotspot edit\n' >> "$TMP/hot_complex.py"
git -C "$TMP" add hot_complex.py
commit "hotspot edit"
if python3 "$CHECK" --repo "$TMP" --base HEAD~1 --top 2 --paths .; then
  echo "expected FAIL for a frequent complex file" >&2
  exit 1
fi

if ! grep -q 'scripts/check-hotspots.py' "$ROOT/.github/workflows/ci.yml"; then
  echo "CI does not run check-hotspots.py" >&2
  exit 1
fi
echo "test-check-hotspots: PASS"
