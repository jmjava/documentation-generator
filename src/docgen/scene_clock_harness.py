"""Execute compiled scene ``construct()`` against the real ``_TimedScene`` clock.

Unit tests that only inspect source strings or ``simulate_reveal_timeline``
have passed while consumer renders still dumped the first board or froze.
This harness runs the **compiled class** with stub Manim mobjects and the
**actual** ``_TimedScene`` methods from ``BOOTSTRAP_HEADER`` — no Manim
install, no ffmpeg. The clock that production uses is the clock we score.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass(frozen=True)
class ClockEvent:
    """One ``play`` / ``wait`` / ``wait_word`` observed during ``construct``."""

    kind: str
    clock_before: float
    duration: float
    anim_kinds: tuple[str, ...] = ()
    skipped: bool = False
    word_index: int | None = None
    word_start: float | None = None

    @property
    def clock_after(self) -> float:
        return float(self.clock_before) + float(self.duration)


@dataclass
class ClockTrace:
    """Full construct run: events plus the final ``_TimedScene._clock``."""

    events: list[ClockEvent] = field(default_factory=list)
    final_clock: float = 0.0

    def wait_word_events(self) -> list[ClockEvent]:
        return [e for e in self.events if e.kind == "wait_word"]

    def play_events(self) -> list[ClockEvent]:
        return [e for e in self.events if e.kind == "play"]

    def skipped_waits(self) -> list[ClockEvent]:
        return [e for e in self.wait_word_events() if e.skipped]

    def emphasis_plays(self) -> list[ClockEvent]:
        return [
            e
            for e in self.play_events()
            if any(k in {"Indicate", "Circumscribe"} for k in e.anim_kinds)
        ]

    def reveal_plays(self) -> list[ClockEvent]:
        reveal_kinds = {"FadeIn", "GrowFromCenter"}
        return [
            e
            for e in self.play_events()
            if any(k in reveal_kinds for k in e.anim_kinds)
            and "FadeOut" not in e.anim_kinds
        ]


class _Dummy:
    """Swallow Manim layout / animation calls; carry a kind tag for scoring."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._kind = str(kwargs.pop("_kind", "mobject"))
        self._role = kwargs.pop("_role", None)
        self._target = args[0] if args else None
        self._label = kwargs.get("label")

    def __getattr__(self, name: str) -> Any:
        def _method(*_a: Any, **_k: Any) -> _Dummy:
            return self

        return _method

    def __mul__(self, other: Any) -> _Dummy:
        return self

    def __rmul__(self, other: Any) -> _Dummy:
        return self

    def __neg__(self) -> _Dummy:
        return self

    def __iter__(self) -> Any:
        return iter(())


class StubScene:
    """Stand-in for ``manim.Scene`` so ``_TimedScene`` can run offline."""

    def __init__(self) -> None:
        self._clock = 0.0
        self.mobjects: list[Any] = []
        self.camera = SimpleNamespace(background_color=None)
        self.events: list[ClockEvent] = []
        self.setup()

    def setup(self) -> None:
        self._clock = 0.0

    def play(self, *animations: Any, run_time: float = 1.0, **_kwargs: Any) -> None:
        kinds = tuple(getattr(a, "_kind", type(a).__name__) for a in animations)
        self.events.append(
            ClockEvent(
                kind="play",
                clock_before=float(self._clock),
                duration=float(run_time),
                anim_kinds=kinds,
            )
        )

    def wait(self, duration: float) -> None:
        self.events.append(
            ClockEvent(
                kind="wait",
                clock_before=float(self._clock),
                duration=float(duration),
            )
        )

    def add(self, *mobjects: Any) -> None:
        self.mobjects.extend(mobjects)

    def remove(self, *_mobjects: Any) -> None:
        return None


def _anim(name: str) -> Any:
    def factory(*args: Any, **kwargs: Any) -> _Dummy:
        d = _Dummy(*args, **kwargs)
        d._kind = name
        if args:
            d._target = args[0]
        return d

    factory.__name__ = name
    return factory


def _extract_timed_scene_src() -> str:
    from docgen.manim_scene_support import BOOTSTRAP_HEADER

    tree = ast.parse(BOOTSTRAP_HEADER)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "_TimedScene":
            src = ast.get_source_segment(BOOTSTRAP_HEADER, node)
            if not src:
                break
            return src.replace("class _TimedScene(Scene):", "class _TimedScene(StubScene):", 1)
    raise RuntimeError("BOOTSTRAP_HEADER is missing class _TimedScene(Scene)")


def _exec_namespace(
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    vec = _Dummy(_kind="dir")
    ns: dict[str, Any] = {
        "StubScene": StubScene,
        "SimpleNamespace": SimpleNamespace,
        "Text": _anim("Text"),
        "Write": _anim("Write"),
        "FadeIn": _anim("FadeIn"),
        "FadeOut": _anim("FadeOut"),
        "GrowFromCenter": _anim("GrowFromCenter"),
        "GrowArrow": _anim("GrowArrow"),
        "Indicate": _anim("Indicate"),
        "Circumscribe": _anim("Circumscribe"),
        "VGroup": _anim("VGroup"),
        "Group": _anim("Group"),
        "Arrow": _anim("Arrow"),
        "DashedVMobject": _anim("DashedVMobject"),
        "ImageMobject": _anim("ImageMobject"),
        "UP": vec,
        "DOWN": vec,
        "LEFT": vec,
        "RIGHT": vec,
        "MANIM_FONT": "Liberation Sans",
        "C_BG": "#1e1e2e",
        "C_ACCENT": "#667eea",
        "C_GREEN": "#42b883",
        "C_ORANGE": "#f9a825",
        "C_BLUE": "#2979ff",
        "C_RED": "#ff5252",
        "C_TEAL": "#26c6da",
        "C_PURPLE": "#ce93d8",
        "C_WHITE": "#cdd6f4",
        "_box": lambda *a, **k: _Dummy(*a, _kind="box", _role="box", label=a[0] if a else ""),
        "_arrow": lambda *a, **k: _Dummy(*a, _kind="arrow", _role="arrow"),
        "_image": lambda *a, **k: _Dummy(*a, _kind="image", _role="image"),
        "_load_timing_words": lambda _key: list(words),
        "_load_timing": lambda _key: list(segments or []),
    }
    exec(_extract_timed_scene_src(), ns)  # noqa: S102 — our bootstrap, not user input
    timed = ns["_TimedScene"]
    orig = timed.wait_until_word

    def _logged_wait_until_word(self: Any, words_arg: Any, index: int) -> None:
        before = float(getattr(self, "_clock", 0.0))
        target: float | None = None
        try:
            if words_arg and 0 <= int(index) < len(words_arg):
                target = float(words_arg[int(index)].get("start", 0.0))
        except (TypeError, ValueError, AttributeError):
            target = None
        orig(self, words_arg, index)
        skipped = target is not None and before > target + 0.05
        self.events.append(
            ClockEvent(
                kind="wait_word",
                clock_before=before,
                duration=0.0,
                skipped=skipped,
                word_index=int(index),
                word_start=target,
            )
        )

    timed.wait_until_word = _logged_wait_until_word
    return ns


def run_compiled_scene_clock(
    class_src: str,
    words: list[dict[str, Any]],
    *,
    segments: list[dict[str, Any]] | None = None,
) -> ClockTrace:
    """Exec ``class_src`` and run ``construct()``. Returns the observed clock."""
    ns = _exec_namespace(words, segments)
    exec(class_src, ns)  # noqa: S102 — compiler output, not user input
    timed = ns["_TimedScene"]
    cls = None
    for value in ns.values():
        if isinstance(value, type) and value is not timed and issubclass(value, timed):
            cls = value
            break
    if cls is None:
        raise RuntimeError("compiled source did not define a _TimedScene subclass")
    scene = cls()
    scene.construct()
    return ClockTrace(events=list(scene.events), final_clock=float(scene._clock))


def clock_contract_violations(
    trace: ClockTrace,
    words: list[dict[str, Any]],
    *,
    audio_end: float = 0.0,
    slack: float = 0.05,
) -> list[str]:
    """Fail-closed checks on an **executed** construct (not the simulator)."""
    from docgen.manim_primitives import (
        DWELL_CLOCK_MARGIN,
        MAX_STATIC_HOLD,
        MIN_DWELL_RUN_TIME,
        audio_end_from_words,
    )

    issues: list[str] = []
    for ev in trace.skipped_waits():
        issues.append(
            f"wait_until_word[{ev.word_index}] no-op: clock {ev.clock_before:.2f}s "
            f"already past spoken start {ev.word_start:.2f}s (first-board dump / issue #66)"
        )

    waits = trace.wait_word_events()
    for i, ev in enumerate(waits):
        nxt = None
        for later in waits[i + 1 :]:
            if later.word_start is not None:
                nxt = float(later.word_start)
                break
        if nxt is None:
            continue
        # Plays after this wait and before the next wait_word must not pass nxt.
        started = False
        for item in trace.events:
            if item is ev:
                started = True
                continue
            if not started:
                continue
            if item.kind == "wait_word":
                break
            if item.kind == "play" and item.clock_after > nxt + slack:
                issues.append(
                    f"overshoot: {item.anim_kinds} ended at {item.clock_after:.2f}s "
                    f"past next wait_word start {nxt:.2f}s"
                )

    end = float(audio_end) if audio_end else float(audio_end_from_words(words) or 0.0)
    allowed_idle = MAX_STATIC_HOLD + MIN_DWELL_RUN_TIME + DWELL_CLOCK_MARGIN + 0.15
    for i, ev in enumerate(waits):
        nxt = None
        for later in waits[i + 1 :]:
            if later.word_start is not None:
                nxt = float(later.word_start)
                break
        if nxt is None:
            nxt = end if end > 0 else None
        if nxt is None:
            continue
        window: list[ClockEvent] = []
        started = False
        for item in trace.events:
            if item is ev:
                started = True
                continue
            if not started:
                continue
            if item.kind == "wait_word":
                break
            window.append(item)
        last_motion = ev.clock_before
        pulses = 0
        for item in window:
            if item.kind == "play":
                last_motion = item.clock_after
                if any(k in {"Indicate", "Circumscribe"} for k in item.anim_kinds):
                    pulses += 1
        idle = float(nxt) - last_motion
        # Author may set emphasis: none. Only fail when we *did* pulse, then froze.
        if pulses >= 1 and idle > allowed_idle:
            issues.append(
                f"stuck hold: {idle:.2f}s idle after last pulse "
                f"(wait_word[{ev.word_index}], max {allowed_idle:.2f}s)"
            )
    return issues


def simulator_exec_drift_violations(
    sim_events: list[Any],
    trace: ClockTrace,
    *,
    slack: float = 0.12,
) -> list[str]:
    """Fail when ``simulate_reveal_timeline`` disagrees with executed construct."""
    issues: list[str] = []
    sim_skips = sum(1 for e in sim_events if getattr(e, "wait_skipped", False))
    exec_skips = len(trace.skipped_waits())
    if sim_skips != exec_skips:
        issues.append(
            f"drift: simulator wait skips={sim_skips} executed skips={exec_skips}"
        )
    sim_pulses = 0
    for ev in sim_events:
        pulses = getattr(ev, "hold_pulses", ()) or ()
        if pulses:
            sim_pulses += len(pulses)
        elif float(getattr(ev, "dwell_run_time", 0.0) or 0.0) > 0:
            sim_pulses += 1
    exec_pulses = len(trace.emphasis_plays())
    if sim_pulses != exec_pulses:
        issues.append(
            f"drift: simulator hold pulses={sim_pulses} executed Indicate/Circumscribe={exec_pulses}"
        )
    paced_sim = [e for e in sim_events if getattr(e, "wait_word", None) is not None]
    paced_exec = trace.wait_word_events()
    for sim, exe in zip(paced_sim, paced_exec):
        if getattr(sim, "wait_skipped", False) or exe.skipped:
            continue
        start = getattr(sim, "word_start", None)
        if start is None or exe.word_start is None:
            continue
        # After a successful wait, executed clock should be on the spoken start.
        if abs(float(exe.word_start) - float(start)) > slack:
            issues.append(
                f"drift: wait_word[{exe.word_index}] sim start {start:.2f} "
                f"exec start {exe.word_start:.2f}"
            )
    return issues
