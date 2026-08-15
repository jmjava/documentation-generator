"""Clock-safe motion math shared by scene-spec compile and tests.

Manim-facing copies of ``_box`` / ``_arrow`` live in ``BOOTSTRAP_HEADER``.
This module stays importable without Manim so unit tests can lock geometry
and dwell budgets independently of a render.
"""

from __future__ import annotations

import math

# Floor when allocating Indicate / Circumscribe after a reveal.
MIN_DWELL_RUN_TIME = 0.35
DEFAULT_DWELL_RUN_TIME = 0.5
# Leave this much clock before the next wait_word so dwell cannot skip it.
DWELL_CLOCK_MARGIN = 0.12

ALLOWED_SHAPES = frozenset({"rounded", "pill", "diamond"})
ALLOWED_REVEALS = frozenset({"fade", "grow", "slide"})
ALLOWED_EMPHASIS = frozenset({"none", "pulse", "ring"})
ALLOWED_DWELL_EMPHASIS = frozenset({"auto", "none"})


def connector_endpoints(
    c1: tuple[float, float],
    half1: tuple[float, float],
    c2: tuple[float, float],
    half2: tuple[float, float],
    buff: float = 0.2,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Axis-aligned bbox edge points facing each other, plus ``buff`` along the ray.

    ``half1`` / ``half2`` are ``(half_width, half_height)`` of each box.
    Used to lock edge-to-edge arrow geometry without importing Manim.
    """
    x1, y1 = c1
    x2, y2 = c2
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return c1, c2

    def _hit(hw: float, hh: float, sx: float, sy: float) -> tuple[float, float]:
        tx = hw / abs(sx) if abs(sx) > 1e-9 else float("inf")
        ty = hh / abs(sy) if abs(sy) > 1e-9 else float("inf")
        t = min(tx, ty)
        return (t * sx, t * sy)

    start_off = _hit(half1[0], half1[1], dx, dy)
    end_off = _hit(half2[0], half2[1], -dx, -dy)
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    start = (x1 + start_off[0] + ux * buff, y1 + start_off[1] + uy * buff)
    end = (x2 + end_off[0] - ux * buff, y2 + end_off[1] - uy * buff)
    return start, end


def resolve_box_emphasis(box: dict, layout: dict | None) -> str:
    """Return ``none`` | ``pulse`` | ``ring``. Omitted box field inherits layout.

    ``layout.dwell_emphasis`` is ``auto`` (default → pulse when budget allows)
    or ``none``. A box-level ``emphasis`` always wins.
    """
    raw = box.get("emphasis") if isinstance(box, dict) else None
    if raw is not None:
        val = str(raw).strip().lower()
        if val == "auto":
            return "pulse"
        return val
    mode = str((layout or {}).get("dwell_emphasis") or "auto").strip().lower()
    if mode == "none":
        return "none"
    return "pulse"


def clamp_title_run_time(
    title_rt: float,
    first_word_start: float | None,
    *,
    min_rt: float = 0.25,
    slack: float = 0.05,
) -> float:
    """Shrink the title ``Write`` so ``_clock`` does not skip the first wait_word."""
    try:
        rt = float(title_rt)
    except (TypeError, ValueError):
        rt = 1.0
    if first_word_start is None:
        return rt
    budget = float(first_word_start) - slack
    if budget <= min_rt:
        return float(min_rt)
    return min(rt, budget)


def compute_dwell_run_time(
    clock: float,
    next_target: float | None,
    *,
    requested: str,
    default_rt: float = DEFAULT_DWELL_RUN_TIME,
) -> float:
    """Seconds of emphasis after a reveal, or 0 if it would race the next wait.

    ``next_target`` is the next paced ``wait_word`` start. ``None`` means this
    is the last reveal — use ``default_rt`` (audio tail still waits after).
    """
    if requested == "none":
        return 0.0
    try:
        default = float(default_rt)
    except (TypeError, ValueError):
        default = DEFAULT_DWELL_RUN_TIME
    if default <= 0:
        return 0.0
    if next_target is None:
        return default
    usable = float(next_target) - float(clock) - DWELL_CLOCK_MARGIN
    if usable < MIN_DWELL_RUN_TIME:
        return 0.0
    return min(default, usable)
