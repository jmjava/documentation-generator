"""Bootstrap external tools so the full test suite runs without skips."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _e2e_in_session(session) -> bool:
    items = getattr(session, "items", None) or []
    for item in items:
        nid = (getattr(item, "nodeid", "") or "").replace("\\", "/")
        if "/e2e/" in nid or nid.startswith("tests/e2e/"):
            return True
    return False


def _chromium_browser_file_present() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        return bool(exe and Path(exe).is_file())
    except Exception:
        return False


def _install_playwright_chromium() -> None:
    """Download the Chromium bundle used by pytest-playwright (no sudo).

    CI (``.github/workflows/ci.yml``) also runs ``playwright install --with-deps chromium``
    before e2e so system libraries are present; locally that step often needs a password,
    so we only run the browser download here.
    """
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    if _chromium_browser_file_present():
        return
    # In CI, apt deps were installed by the workflow; --with-deps is a no-op for browsers
    # but can help if the first install left a partial state. Skip without password/sudo.
    if sys.platform.startswith("linux") and os.environ.get("CI") == "true":
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
            check=True,
        )


def _needs_cli_render_tools(session) -> bool:
    """``demo_function`` VHS+ffmpeg integration tests (see ``tests/_render_tools_bootstrap.py``)."""
    for item in getattr(session, "items", None) or []:
        nid = getattr(item, "nodeid", "") or ""
        base = nid.split("[")[0]
        if base.endswith("::test_render_cli_kind_emits_artifacts"):
            return True
        if base.endswith("::test_render_warns_when_openai_key_missing"):
            return True
    return False


_FFMPEG_ONLY_VALIDATE_TESTS = frozenset(
    {
        "tests/test_validate.py::TestComposeGuard::test_compose_rejects_short_video",
        "tests/test_validate.py::TestComposeGuard::test_compose_allows_matching_durations",
        "tests/test_validate.py::TestComposeGuard::test_compose_nonstrict_warns",
        "tests/test_validate.py::TestValidateSegmentIntegration::test_static_video_does_not_fail_pre_push",
    }
)


def _needs_ffmpeg_only_bootstrap(session) -> bool:
    for item in getattr(session, "items", None) or []:
        base = (getattr(item, "nodeid", "") or "").split("[")[0]
        if base in _FFMPEG_ONLY_VALIDATE_TESTS:
            return True
    return False


def pytest_collection_finish(session) -> None:
    if getattr(session.config.option, "collectonly", False):
        return
    if _e2e_in_session(session) and not _chromium_browser_file_present():
        _install_playwright_chromium()
    if _needs_cli_render_tools(session):
        from tests._render_tools_bootstrap import bootstrap_cli_render_toolchain

        bootstrap_cli_render_toolchain()
    elif _needs_ffmpeg_only_bootstrap(session):
        from tests._render_tools_bootstrap import bootstrap_ffmpeg_for_tests

        bootstrap_ffmpeg_for_tests()
