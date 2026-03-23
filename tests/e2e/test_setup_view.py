"""Playwright e2e tests for the Setup view of the docgen wizard."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def navigate_to_wizard(page: Page, wizard_url: str):
    page.goto(wizard_url)
    page.wait_for_load_state("networkidle")


class TestSetupNavigation:
    def test_page_title(self, page: Page):
        expect(page).to_have_title("docgen wizard")

    def test_brand_visible(self, page: Page):
        expect(page.locator(".brand")).to_have_text("docgen wizard")

    def test_setup_is_default_view(self, page: Page):
        setup_view = page.locator("#view-setup")
        expect(setup_view).to_be_visible()
        production_view = page.locator("#view-production")
        expect(production_view).to_be_hidden()

    def test_nav_buttons_exist(self, page: Page):
        expect(page.locator(".nav-btn", has_text="Setup")).to_be_visible()
        expect(page.locator(".nav-btn", has_text="Production")).to_be_visible()


class TestFileTree:
    def test_file_tree_loads(self, page: Page):
        tree = page.locator("#file-tree")
        expect(tree).to_be_visible()
        tree.wait_for(state="attached")
        items = page.locator("#file-tree .tree-item")
        expect(items.first).to_be_visible()

    def test_md_files_appear(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        files = page.locator("#file-tree .tree-file")
        count = files.count()
        assert count >= 3, f"Expected at least 3 .md files, got {count}"

    def test_readme_in_tree(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        expect(page.locator("#file-tree label", has_text="README.md")).to_be_visible()

    def test_directory_expands(self, page: Page):
        page.wait_for_selector("#file-tree .tree-dir")
        docs_dir = page.locator("#file-tree .tree-dir", has_text="docs")
        expect(docs_dir).to_be_visible()
        docs_dir.click()
        expect(docs_dir).to_have_class(re.compile(r"open"))

    def test_select_file_checkbox(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        cb = page.locator('#file-tree input[type="checkbox"]').first
        cb.check()
        expect(cb).to_be_checked()

    def test_snippet_shown(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        snippets = page.locator("#file-tree .snippet")
        assert snippets.count() > 0


class TestSegmentMapper:
    def test_add_segment_button(self, page: Page):
        btn = page.locator("#btn-add-segment")
        expect(btn).to_be_visible()
        btn.click()
        expect(page.locator(".segment-slot")).to_have_count(1)

    def test_add_multiple_segments(self, page: Page):
        btn = page.locator("#btn-add-segment")
        btn.click()
        btn.click()
        btn.click()
        expect(page.locator(".segment-slot")).to_have_count(3)

    def test_remove_segment(self, page: Page):
        page.locator("#btn-add-segment").click()
        page.locator("#btn-add-segment").click()
        expect(page.locator(".segment-slot")).to_have_count(2)
        page.locator(".btn-remove-seg").first.click()
        expect(page.locator(".segment-slot")).to_have_count(1)

    def test_segment_name_editable(self, page: Page):
        page.locator("#btn-add-segment").click()
        name_input = page.locator(".segment-slot .seg-header input").first
        name_input.fill("my-custom-name")
        expect(name_input).to_have_value("my-custom-name")

    def test_auto_group_with_selection(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        # Expand all directories so nested checkboxes become visible
        dirs = page.locator("#file-tree .tree-dir")
        for i in range(dirs.count()):
            d = dirs.nth(i)
            if d.is_visible():
                d.click()
                page.wait_for_timeout(100)
        # Select all visible checkboxes
        checkboxes = page.locator('#file-tree input[type="checkbox"]')
        for i in range(checkboxes.count()):
            cb = checkboxes.nth(i)
            if cb.is_visible():
                cb.check()
        page.locator("#btn-auto-group").click()
        slots = page.locator(".segment-slot")
        assert slots.count() >= 1, "Auto-group should create at least one segment"

    def test_generate_disabled_without_segments(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        checkboxes = page.locator('#file-tree input[type="checkbox"]')
        checkboxes.first.check()
        expect(page.locator("#btn-generate")).to_be_disabled()

    def test_generate_disabled_without_files(self, page: Page):
        page.locator("#btn-add-segment").click()
        expect(page.locator("#btn-generate")).to_be_disabled()

    def test_generate_enabled_with_files_and_segments(self, page: Page):
        page.wait_for_selector("#file-tree .tree-file")
        checkboxes = page.locator('#file-tree input[type="checkbox"]')
        checkboxes.first.check()
        page.locator("#btn-add-segment").click()
        expect(page.locator("#btn-generate")).to_be_enabled()


class TestGuidanceTextarea:
    def test_guidance_textarea_visible(self, page: Page):
        expect(page.locator("#guidance")).to_be_visible()

    def test_guidance_accepts_input(self, page: Page):
        ta = page.locator("#guidance")
        ta.fill("Focus on CI/CD pipeline and developer experience.")
        expect(ta).to_have_value("Focus on CI/CD pipeline and developer experience.")
