"""Bootstrap external tools (just ffmpeg) so the full test suite runs without skips.

Favor tests that guard CLI and config behavior downstream apps rely on; see
AGENTS.md "Testing (downstream relevance)".
"""

from __future__ import annotations

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
    if _needs_ffmpeg_only_bootstrap(session):
        from tests._render_tools_bootstrap import bootstrap_ffmpeg_for_tests

        bootstrap_ffmpeg_for_tests()
