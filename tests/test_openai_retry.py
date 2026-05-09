"""Tests for :mod:`docgen.openai_retry`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


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
