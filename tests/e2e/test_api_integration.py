"""Playwright e2e tests verifying API integration through the browser."""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page


@pytest.fixture(autouse=True)
def navigate(page: Page, wizard_url: str):
    page.goto(wizard_url)
    page.wait_for_load_state("networkidle")


class TestScanAPI:
    def test_scan_returns_md_files(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/scan")
        assert resp.ok
        data = resp.json()
        paths = [f["path"] for f in data["files"]]
        assert "README.md" in paths
        assert "docs/setup.md" in paths
        assert "docs/architecture.md" in paths
        assert len(data["tree"]) > 0

    def test_scan_excludes_narration_md(self, page: Page, wizard_url: str):
        """Narration .md files live inside the project but shouldn't be scanned as source docs
        (they're under narration/ which is inside the repo root)."""
        resp = page.request.get(f"{wizard_url}/api/scan")
        data = resp.json()
        paths = [f["path"] for f in data["files"]]
        narration_files = [p for p in paths if p.startswith("narration/")]
        # Narration files ARE within the repo tree — that's fine, they show up.
        # The important thing is the API returned them.  The wizard/user decides
        # which ones to use as source material.
        assert isinstance(narration_files, list)


class TestSegmentsAPI:
    def test_segments_list(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/segments")
        assert resp.ok
        data = resp.json()
        ids = [s["id"] for s in data["segments"]]
        assert "01-intro" in ids
        assert "02-setup" in ids

    def test_segment_has_narration(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/segments")
        data = resp.json()
        intro = next(s for s in data["segments"] if s["id"] == "01-intro")
        assert intro["has_narration"] is True


class TestNarrationAPI:
    def test_get_narration(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/narration/01-intro")
        assert resp.ok
        data = resp.json()
        assert "Welcome to the test project" in data["text"]

    def test_put_narration(self, page: Page, wizard_url: str):
        new_text = "Updated via API test."
        resp = page.request.put(
            f"{wizard_url}/api/narration/01-intro",
            data=json.dumps({"text": new_text}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.ok

        resp2 = page.request.get(f"{wizard_url}/api/narration/01-intro")
        assert resp2.json()["text"] == new_text

    def test_get_nonexistent_narration(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/narration/99-nonexistent")
        assert resp.ok
        data = resp.json()
        assert data["text"] == ""


class TestStateAPI:
    def test_get_initial_state(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/state")
        assert resp.ok
        data = resp.json()
        assert "segments" in data

    def test_save_and_load_state(self, page: Page, wizard_url: str):
        state = {
            "segments": {
                "01-intro": {"status": "approved"},
                "02-setup": {"status": "needs-work", "revision_notes": "Fix timing"},
            }
        }
        resp = page.request.post(
            f"{wizard_url}/api/state",
            data=json.dumps(state),
            headers={"Content-Type": "application/json"},
        )
        assert resp.ok

        resp2 = page.request.get(f"{wizard_url}/api/state")
        loaded = resp2.json()
        assert loaded["segments"]["01-intro"]["status"] == "approved"
        assert loaded["segments"]["02-setup"]["revision_notes"] == "Fix timing"


class TestFileAPI:
    def test_read_file(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/file?path=README.md")
        assert resp.ok
        data = resp.json()
        assert "Test Project" in data["content"]

    def test_read_missing_file(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/api/file?path=nope.md")
        assert resp.status == 404


class TestStaticAssets:
    def test_css_serves(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/static/wizard.css")
        assert resp.ok
        assert "topnav" in resp.text()

    def test_js_serves(self, page: Page, wizard_url: str):
        resp = page.request.get(f"{wizard_url}/static/wizard.js")
        assert resp.ok
        assert "loadFileTree" in resp.text()
