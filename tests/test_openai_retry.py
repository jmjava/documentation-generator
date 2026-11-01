"""Tests for :mod:`docgen.openai_retry`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_infinite_retry_after_uses_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Infinity must not become time.sleep(inf)."""
    from types import SimpleNamespace

    from docgen.openai_retry import _rate_limit_delay_sec

    monkeypatch.setattr("docgen.openai_retry.random.uniform", lambda _a, _b: 0.0)
    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "Infinity"}))
    assert _rate_limit_delay_sec(exc, 0) == 1.0


def test_numeric_retry_after_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from docgen.openai_retry import _rate_limit_delay_sec

    monkeypatch.setattr("docgen.openai_retry.random.uniform", lambda _a, _b: 0.0)
    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "3"}))
    assert _rate_limit_delay_sec(exc, 0) == 3.0


def test_rate_limit_retries_then_succeeds() -> None:
    import openai

    from docgen.openai_retry import call_with_rate_limit_retries

    calls = {"n": 0}

    def fn() -> int:
        calls["n"] += 1
        if calls["n"] < 3:
            raise openai.RateLimitError(
                message="429",
                response=MagicMock(headers={}),
                body=None,
            )
        return 42

    with patch("docgen.openai_retry.time.sleep"):
        assert call_with_rate_limit_retries(fn) == 42
    assert calls["n"] == 3


def test_rate_limit_exhausted_reraises() -> None:
    import openai

    from docgen.openai_retry import call_with_rate_limit_retries

    def fn() -> None:
        raise openai.RateLimitError(
            message="429",
            response=MagicMock(headers={}),
            body=None,
        )

    with patch("docgen.openai_retry.time.sleep"):
        with pytest.raises(openai.RateLimitError):
            call_with_rate_limit_retries(fn)
