"""Bootstrap external tools (just ffmpeg) so the full test suite runs without skips.

Favor tests that guard CLI and config behavior downstream apps rely on; see
AGENTS.md "Testing (downstream relevance)".
"""

from __future__ import annotations

import pytest

_CLEAR_ENV = (
    "DOCGEN_REPO",
    "DOCGEN_AI_PROVIDER",
    "DOCGEN_AI_BASE_URL",
    "DOCGEN_AI_API_KEY_ENV",
    "DOCGEN_REPO_CACHE",
)

_AI_KEY_ENVS = (
    "CURSOR_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DOCGEN_AI_PROVIDER",
    "DOCGEN_AI_BASE_URL",
    "DOCGEN_AI_API_KEY_ENV",
)


@pytest.fixture(autouse=True)
def _clear_docgen_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider/repo env from leaking into CLI and AI-client tests."""
    for key in _CLEAR_ENV:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop AI keys so provider resolution tests do not inherit the host env."""
    for key in _AI_KEY_ENVS:
        monkeypatch.delenv(key, raising=False)


_FFMPEG_ONLY_VALIDATE_TESTS = frozenset(
    {
        "tests/test_validate.py::TestComposeGuard::test_compose_rejects_short_video",
        "tests/test_validate.py::TestComposeGuard::test_compose_allows_matching_durations",
        "tests/test_validate.py::TestComposeGuard::test_compose_nonstrict_warns",
        "tests/test_validate.py::TestValidateSegmentIntegration::test_static_video_fails_pre_push",
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
    if _needs_ffmpeg_only_bootstrap(session):
        from tests._render_tools_bootstrap import bootstrap_ffmpeg_for_tests

        bootstrap_ffmpeg_for_tests()
