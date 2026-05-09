"""Retry helpers for transient OpenAI API failures (notably TPM/RPM 429s)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# Enough for short burst limits + a minute-scale TPM window when many tests
# or segments run back-to-back.
_MAX_RATE_LIMIT_ATTEMPTS = 10
_BASE_DELAY_SEC = 1.0
_MAX_BACKOFF_SEC = 120.0


def call_with_rate_limit_retries(fn: Callable[[], T]) -> T:
    """Run ``fn``; on :class:`openai.RateLimitError`, sleep with backoff and retry.

    Uses ``Retry-After`` when the response exposes it; otherwise exponential
    backoff with light jitter. Non-rate-limit errors propagate immediately.

    After ``_MAX_RATE_LIMIT_ATTEMPTS`` failures, re-raises the last
    :class:`openai.RateLimitError`.
    """
    import openai

    for attempt in range(_MAX_RATE_LIMIT_ATTEMPTS):
        try:
            return fn()
        except openai.RateLimitError as exc:
            if attempt >= _MAX_RATE_LIMIT_ATTEMPTS - 1:
                raise
            delay = _rate_limit_delay_sec(exc, attempt)
            time.sleep(delay)


def _rate_limit_delay_sec(exc: BaseException, attempt: int) -> float:
    retry_after: float | None = None
    resp = getattr(exc, "response", None)
    if resp is not None:
        raw = resp.headers.get("retry-after")
        if raw:
            try:
                retry_after = float(raw)
            except ValueError:
                retry_after = None
    if retry_after is not None and retry_after > 0:
        delay = retry_after
    else:
        delay = min(_MAX_BACKOFF_SEC, _BASE_DELAY_SEC * (2**attempt))
    jitter = random.uniform(0, max(0.05, 0.15 * delay))
    return delay + jitter
