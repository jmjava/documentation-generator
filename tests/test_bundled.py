"""Bundled package resources (pip install)."""

from __future__ import annotations

from docgen.bundled import catalog_workflow_issue_template_path, read_catalog_workflow_issue_template


def test_catalog_workflow_issue_template_exists() -> None:
    p = catalog_workflow_issue_template_path()
    assert p.is_file(), f"missing bundled template: {p}"


def test_catalog_workflow_issue_template_has_summary() -> None:
    text = read_catalog_workflow_issue_template()
    assert "## Summary" in text
    assert "docgen.catalog.yaml" in text
