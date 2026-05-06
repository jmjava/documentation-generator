#!/usr/bin/env bash
# Open a GitHub issue in a parent/consuming repo with a checklist for implementing
# the docgen discovery catalog CI workflow. Requires GitHub CLI: https://cli.github.com/
#
# Usage:
#   ./scripts/gh-issue-catalog-workflow.sh owner/repo
#   TARGET_REPO=owner/repo ./scripts/gh-issue-catalog-workflow.sh
#
# Optional:
#   ISSUE_TITLE="..." ./scripts/gh-issue-catalog-workflow.sh owner/repo
#   DRY_RUN=1 ./scripts/gh-issue-catalog-workflow.sh owner/repo   # print gh command only

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Bundled in the pip package; when running from a git clone use the source tree copy.
BODY_FILE="${ROOT}/src/docgen/templates/github-issue-docgen-catalog-workflow.md"
if [[ ! -f "${BODY_FILE}" ]] && command -v docgen >/dev/null 2>&1; then
  BODY_FILE="$(docgen self catalog-issue-template --path)"
fi
REPO="${1:-${TARGET_REPO:-}}"

if [[ -z "${REPO}" ]]; then
  echo "usage: $0 <owner/repo>" >&2
  echo "   or: TARGET_REPO=owner/repo $0" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh (GitHub CLI) not found. Install it, or paste the template manually:" >&2
  echo "  ${BODY_FILE}" >&2
  exit 1
fi

if [[ ! -f "${BODY_FILE}" ]]; then
  echo "error: missing body file: ${BODY_FILE}" >&2
  exit 1
fi

TITLE="${ISSUE_TITLE:-Implement docgen catalog workflow in CI (incremental regen + overrides)}"

if [[ -n "${DRY_RUN:-}" ]]; then
  echo gh issue create --repo "${REPO}" --title "${TITLE}" --body-file "${BODY_FILE}"
  exit 0
fi

gh issue create --repo "${REPO}" --title "${TITLE}" --body-file "${BODY_FILE}"
