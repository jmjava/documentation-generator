"""Playwright e2e tests for the Production view of the docgen wizard."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(autouse=True)
def navigate_to_production(page: Page, wizard_url: str):
    page.goto(wizard_url)
    page.wait_for_load_state("networkidle")
    page.locator(".nav-btn", has_text="Production").click()
    page.wait_for_load_state("networkidle")


class TestProductionNavigation:
    def test_production_view_visible(self, page: Page):
        expect(page.locator("#view-production")).to_be_visible()
        expect(page.locator("#view-setup")).to_be_hidden()

    def test_switch_back_to_setup(self, page: Page):
        page.locator(".nav-btn", has_text="Setup").click()
        expect(page.locator("#view-setup")).to_be_visible()
        expect(page.locator("#view-production")).to_be_hidden()


class TestSegmentSidebar:
    def test_segment_list_renders(self, page: Page):
        items = page.locator("#segment-list li")
        expect(items).to_have_count(2)

    def test_segment_names(self, page: Page):
        expect(page.locator("#segment-list li", has_text="01-intro")).to_be_visible()
        expect(page.locator("#segment-list li", has_text="02-setup")).to_be_visible()

    def test_progress_bar_exists(self, page: Page):
        expect(page.locator("#progress-bar-container")).to_be_visible()
        expect(page.locator("#progress-text")).to_contain_text("0 / 2 approved")

    def test_segment_badges_default_draft(self, page: Page):
        badges = page.locator("#segment-list .badge")
        for i in range(badges.count()):
            expect(badges.nth(i)).to_have_text("draft")


class TestSegmentReview:
    def test_placeholder_before_selection(self, page: Page):
        expect(page.locator("#no-segment-selected")).to_be_visible()
        expect(page.locator("#segment-review")).to_be_hidden()

    def test_select_segment_shows_review(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        expect(page.locator("#segment-review")).to_be_visible()
        expect(page.locator("#no-segment-selected")).to_be_hidden()
        expect(page.locator("#review-segment-title")).to_contain_text("01-intro")

    def test_narration_tab_default(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        narration_tab = page.locator('.tab-content[data-tab="narration"]')
        expect(narration_tab).to_have_class(re.compile(r"active"))

    def test_narration_text_loaded(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        editor = page.locator("#narration-editor")
        expect(editor).to_be_visible()
        expect(editor).to_have_value(re.compile(r"Welcome to the test project"))

    def test_switch_to_audio_tab(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        page.locator('.tab-btn[data-tab="audio"]').click()
        expect(page.locator('.tab-content[data-tab="audio"]')).to_have_class(re.compile(r"active"))
        expect(page.locator("#audio-status")).to_be_visible()

    def test_switch_to_video_tab(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        page.locator('.tab-btn[data-tab="video"]').click()
        expect(page.locator('.tab-content[data-tab="video"]')).to_have_class(re.compile(r"active"))
        expect(page.locator("#video-status")).to_be_visible()


class TestNarrationEditing:
    def test_edit_narration_text(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        editor = page.locator("#narration-editor")
        editor.fill("Updated narration content for testing.")
        expect(editor).to_have_value("Updated narration content for testing.")

    def test_save_narration(self, page: Page):
        # Wait for the narration GET to complete before editing
        with page.expect_response("**/api/narration/01-intro"):
            page.locator("#segment-list li", has_text="01-intro").click()

        editor = page.locator("#narration-editor")
        expect(editor).to_have_value(re.compile(r"Welcome to the test project"))
        editor.fill("Saved narration text from Playwright test.")

        # Wait for the PUT to complete
        with page.expect_response(lambda r: "narration/01-intro" in r.url and r.request.method == "PUT"):
            page.locator("#btn-save-narration").click()

        # Switch away and back to force a fresh GET
        with page.expect_response("**/api/narration/02-setup"):
            page.locator("#segment-list li", has_text="02-setup").click()
        with page.expect_response("**/api/narration/01-intro"):
            page.locator("#segment-list li", has_text="01-intro").click()

        expect(editor).to_have_value("Saved narration text from Playwright test.")

    def test_navigate_between_segments(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        expect(page.locator("#review-segment-title")).to_contain_text("01-intro")
        page.locator("#btn-next-seg").click()
        expect(page.locator("#review-segment-title")).to_contain_text("02-setup")
        page.locator("#btn-prev-seg").click()
        expect(page.locator("#review-segment-title")).to_contain_text("01-intro")


class TestSegmentStatus:
    def test_approve_segment(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        page.locator("#btn-approve").click()
        page.wait_for_timeout(300)

        badge = page.locator("#segment-list li", has_text="01-intro").locator(".badge")
        expect(badge).to_have_text("approved")
        expect(page.locator("#progress-text")).to_contain_text("1 / 2 approved")

    def test_approve_all_updates_progress(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        page.locator("#btn-approve").click()
        page.wait_for_timeout(200)
        # After approving 01-intro, should auto-navigate to 02-setup
        page.locator("#btn-approve").click()
        page.wait_for_timeout(300)
        expect(page.locator("#progress-text")).to_contain_text("2 / 2 approved")

    def test_status_badge_reflects_state(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        badge = page.locator("#review-status-badge")
        expect(badge).to_have_text("draft")


class TestActionButtons:
    def test_action_buttons_visible(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        expect(page.locator("#btn-redo-all")).to_be_visible()
        expect(page.locator("#btn-flag-rework")).to_be_visible()
        expect(page.locator("#btn-approve")).to_be_visible()

    def test_pipeline_buttons_visible_in_video_tab(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        page.locator('.tab-btn[data-tab="video"]').click()
        expect(page.locator("#btn-redo-vhs")).to_be_visible()
        expect(page.locator("#btn-redo-manim")).to_be_visible()
        expect(page.locator("#btn-redo-compose")).to_be_visible()
        expect(page.locator("#btn-run-validate")).to_be_visible()

    def test_tts_button_visible_in_audio_tab(self, page: Page):
        page.locator("#segment-list li", has_text="01-intro").click()
        page.locator('.tab-btn[data-tab="audio"]').click()
        expect(page.locator("#btn-redo-tts")).to_be_visible()
