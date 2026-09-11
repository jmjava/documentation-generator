#!/usr/bin/env bash
# Required CI check: invoke `docgen validate` on a scratch `init` bundle.
# No in-repo dogfood tree. A listed segment with no recordings must FAIL
# (exit 1). If default validate starts exiting 0 here, this job goes red.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${DOCGEN:-}" ]]; then
  :
elif [[ -x "${root}/.venv/bin/docgen" ]]; then
  DOCGEN="${root}/.venv/bin/docgen"
else
  DOCGEN="docgen"
fi

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

git -C "$scratch" init -q
git -C "$scratch" config user.email "ci@example.test"
git -C "$scratch" config user.name "CI"

"$DOCGEN" --repo "$scratch" init --defaults
bundle="$scratch/docs/demos"
test -f "$bundle/docgen.yaml"
test -f "$bundle/narration/01-intro.md"
# Init lists segment 01 and creates no recordings — default validate must fail.
test -z "$(find "$bundle/recordings" -name '*.mp4' -print -quit)"

set +e
out="$("$DOCGEN" --config "$bundle/docgen.yaml" validate 2>&1)"
rc=$?
set -e
printf '%s\n' "$out"

if [[ "$rc" -eq 0 ]]; then
  echo "expected docgen validate to exit 1 on a scratch init bundle with no recordings" >&2
  exit 1
fi
if [[ "$rc" -ne 1 ]]; then
  echo "expected docgen validate exit 1, got $rc" >&2
  exit 1
fi
printf '%s\n' "$out" | grep -q "FAIL" || {
  echo "expected FAIL in validate output" >&2
  exit 1
}
printf '%s\n' "$out" | grep -q "recording_exists" || {
  echo "expected recording_exists in validate output" >&2
  exit 1
}

echo "ci-validate-scratch-bundle: PASS (docgen validate exited $rc on missing recordings)"
