"""Clock-safe motion math shared by scene-spec compile and tests.

Manim-facing copies of ``_box`` / ``_arrow`` live in ``BOOTSTRAP_HEADER``.
This module stays importable without Manim so unit tests can lock geometry
and dwell budgets independently of a render.
"""

from __future__ import annotations

import math

from dataclasses import dataclass

# Floor when allocating Indicate / Circumscribe after a reveal.
MIN_DWELL_RUN_TIME = 0.35
DEFAULT_DWELL_RUN_TIME = 0.5
# Leave this much clock before the next wait_word so dwell cannot skip it.
DWELL_CLOCK_MARGIN = 0.12
# Long subject-beat holds: pulse again before the board sits still this long.
MAX_STATIC_HOLD = 4.0
# Do not insert a mid-hold wait shorter than this (avoids stutter after the first pulse).
MIN_HOLD_RENEW_WAIT = 1.2
# Safety cap so a multi-minute hold cannot emit unbounded Indicate lines.
MAX_HOLD_PULSES = 20

ALLOWED_SHAPES = frozenset({"rounded", "pill", "diamond"})
ALLOWED_REVEALS = frozenset({"fade", "grow", "slide"})
ALLOWED_EMPHASIS = frozenset({"none", "pulse", "ring"})
ALLOWED_DWELL_EMPHASIS = frozenset({"auto", "none"})


@dataclass(frozen=True)
class HoldPulse:
    """One Indicate / Circumscribe after a reveal, optionally after ``timed_wait``."""

    wait_before: float
    run_time: float
    emphasis: str


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


def plan_hold_pulses(
    clock_after_reveal: float,
    next_deadline: float | None,
    *,
    requested: str,
    default_rt: float = DEFAULT_DWELL_RUN_TIME,
) -> tuple[HoldPulse, ...]:
    """Clock-safe pulses for a subject-beat hold.

    The first pulse is immediate (same as a single dwell). Further pulses fire
    after ``timed_wait`` so the board does not sit still longer than
    ``MAX_STATIC_HOLD``, always leaving ``DWELL_CLOCK_MARGIN`` before
    ``next_deadline``.
    """
    first = compute_dwell_run_time(
        clock_after_reveal,
        next_deadline,
        requested=requested,
        default_rt=default_rt,
    )
    if first < MIN_DWELL_RUN_TIME:
        return ()
    pulses = [HoldPulse(wait_before=0.0, run_time=float(first), emphasis=requested)]
    clock = float(clock_after_reveal) + float(first)
    if next_deadline is None:
        return tuple(pulses)

    deadline = float(next_deadline)
    while len(pulses) < MAX_HOLD_PULSES:
        leftover = deadline - clock
        probe = compute_dwell_run_time(
            clock + MIN_HOLD_RENEW_WAIT,
            deadline,
            requested=requested,
            default_rt=default_rt,
        )
        if probe < MIN_DWELL_RUN_TIME:
            break
        max_wait = leftover - probe - DWELL_CLOCK_MARGIN
        if max_wait < MIN_HOLD_RENEW_WAIT:
            break
        wait = min(MAX_STATIC_HOLD, max_wait)
        pulse_rt = compute_dwell_run_time(
            clock + wait,
            deadline,
            requested=requested,
            default_rt=default_rt,
        )
        if pulse_rt < MIN_DWELL_RUN_TIME:
            break
        pulses.append(
            HoldPulse(wait_before=float(wait), run_time=float(pulse_rt), emphasis=requested)
        )
        clock += wait + pulse_rt
    return tuple(pulses)


def hold_span_seconds(pulses: tuple[HoldPulse, ...] | list[HoldPulse]) -> float:
    """Clock advanced by the hold plan after the reveal FadeIn."""
    return sum(float(p.wait_before) + float(p.run_time) for p in pulses)


def audio_end_from_words(words: list[dict] | None) -> float | None:
    """Latest word ``end`` in a Whisper-shaped ``words`` list, or ``None``."""
    end = 0.0
    for word in words or []:
        if not isinstance(word, dict):
            continue
        try:
            end = max(end, float(word.get("end", 0.0)))
        except (TypeError, ValueError):
            continue
    return end if end > 0 else None
