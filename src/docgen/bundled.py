"""Bundled files shipped inside the ``docgen`` distribution (pip install)."""

from __future__ import annotations

from pathlib import Path

_CATALOG_WORKFLOW_ISSUE = "github-issue-docgen-catalog-workflow.md"


def catalog_workflow_issue_template_path() -> Path:
    """Absolute path to the GitHub issue body template for the catalog CI workflow."""
    return Path(__file__).resolve().parent / "templates" / _CATALOG_WORKFLOW_ISSUE


def read_catalog_workflow_issue_template() -> str:
    p = catalog_workflow_issue_template_path()
    return p.read_text(encoding="utf-8")
