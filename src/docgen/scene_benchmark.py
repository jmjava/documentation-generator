"""Fixed scene-timing benchmark corpus and scorer.

Run ``docgen benchmark`` after a clock / compile change. Cases are **standard
scripts** (spec + Whisper-shaped words) that encode production failure modes.
The scorer executes compiled ``construct()`` on the real ``_TimedScene`` clock
(see ``scene_clock_harness``) and diffs the result against a committed baseline.

Quality cases must not grow defects or lose quality points. Control cases must
keep failing — they prove the scorer still detects the historical bug.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from docgen.manim_primitives import audio_end_from_words
from docgen.scene_asset_validate import hold_idle_violations
from docgen.scene_clock_harness import (
    ClockTrace,
    clock_contract_violations,
    run_compiled_scene_clock,
    simulator_exec_drift_violations,
)
from docgen.scene_spec import (
    compile_scene_class,
    reveal_cadence_violations,
    simulate_reveal_timeline,
)

BASELINE_NAME = "baseline.json"


def benchmark_data_dir() -> Path:
    return Path(__file__).resolve().parent / "benchmark_data"


def default_baseline_path() -> Path:
    return benchmark_data_dir() / BASELINE_NAME


@dataclass(frozen=True)
class BenchmarkCase:
    """One standard script: declarative spec + timing words."""

    id: str
    title: str
    spec: dict[str, Any]
    words: list[dict[str, Any]]
    role: str = "quality"  # quality | control
    compile_with_words: bool = True


@dataclass
class CaseScore:
    case_id: str
    title: str
    role: str
    wait_skips: int
    overshoots: int
    hold_idle_violations: int
    cadence_violations: int
    sim_drift: int
    mid_hold_pulses: int
    box_reveals: int
    last_motion_frac: float
    audio_end: float
    defect_points: int
    quality_points: int
    score: int
    issues: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "wait_skips": self.wait_skips,
            "overshoots": self.overshoots,
            "hold_idle_violations": self.hold_idle_violations,
            "cadence_violations": self.cadence_violations,
            "sim_drift": self.sim_drift,
            "mid_hold_pulses": self.mid_hold_pulses,
            "box_reveals": self.box_reveals,
            "last_motion_frac": round(self.last_motion_frac, 4),
            "defect_points": self.defect_points,
            "quality_points": self.quality_points,
            "score": self.score,
        }


def _box(
    label: str,
    *,
    wait_word: int | None = None,
    emphasis: str | None = None,
    reveal: str | None = None,
    shape: str | None = None,
    color: str = "C_GREEN",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": label,
        "color": color,
        "width": 3.0,
        "height": 0.8,
        "font_size": 18,
    }
    if wait_word is not None:
        out["wait_word"] = wait_word
    if emphasis is not None:
        out["emphasis"] = emphasis
    if reveal is not None:
        out["reveal"] = reveal
    if shape is not None:
        out["shape"] = shape
    return out


def _spec(
    case_id: str,
    boxes: list[dict[str, Any]],
    *,
    layout: dict[str, Any] | None = None,
    pages: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    run_time: float = 1.5,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "segment_id": "01",
        "class_name": "BenchScene",
        "timing_key": case_id,
        "title": {"text": "Benchmark", "font_size": 36, "color": "C_WHITE"},
    }
    if pages is not None:
        spec["pages"] = pages
    else:
        spec["rows"] = [{"run_time": run_time, "boxes": boxes}]
    if layout:
        spec["layout"] = layout
    if edges:
        spec["edges"] = edges
    return spec


def standard_cases() -> list[BenchmarkCase]:
    """Committed corpus. Add a case here when a new production failure shows up."""
    tight = [
        {"word": "Alpha", "start": 1.2, "end": 1.4},
        {"word": "Beta", "start": 1.6, "end": 1.8},
        {"word": "Gamma", "start": 2.0, "end": 2.2},
        {"word": "tail", "start": 40.0, "end": 40.5},
    ]
    cascade_boxes = [
        _box("Alpha", wait_word=0),
        _box("Beta", wait_word=1),
        _box("Gamma", wait_word=2),
    ]
    wide = [
        {"word": "Alpha", "start": 1.2, "end": 1.4},
        {"word": "Beta", "start": 8.0, "end": 8.3},
        {"word": "Gamma", "start": 16.0, "end": 16.3},
        {"word": "tail", "start": 24.0, "end": 24.4},
    ]
    return [
        BenchmarkCase(
            id="issue66_tight_clamped",
            title="Tight words + compile clamp (issue #66 must stay fixed)",
            spec=_spec("issue66_tight_clamped", cascade_boxes, run_time=1.5),
            words=tight,
            role="quality",
            compile_with_words=True,
        ),
        BenchmarkCase(
            id="issue66_tight_unclamped",
            title="Control: same spec compiled without words (historical dump)",
            spec=_spec("issue66_tight_unclamped", cascade_boxes, run_time=1.5),
            words=tight,
            role="control",
            compile_with_words=False,
        ),
        BenchmarkCase(
            id="early_title",
            title="First spoken label at 0.55s — title Write must not skip it",
            spec=_spec(
                "early_title",
                [_box("Alpha", wait_word=0), _box("Beta", wait_word=1)],
                run_time=0.8,
            ),
            words=[
                {"word": "Alpha", "start": 0.55, "end": 0.7},
                {"word": "Beta", "start": 4.0, "end": 4.2},
                {"word": "tail", "start": 8.0, "end": 8.3},
            ],
        ),
        BenchmarkCase(
            id="wide_hold",
            title="Long subject-beat holds must pulse more than once",
            spec=_spec("wide_hold", cascade_boxes, run_time=0.8),
            words=wide,
        ),
        BenchmarkCase(
            id="emphasis_none",
            title="Author opt-out: wide holds with emphasis none stay still",
            spec=_spec(
                "emphasis_none",
                [
                    _box("Alpha", wait_word=0, emphasis="none"),
                    _box("Beta", wait_word=1, emphasis="none"),
                ],
                layout={"dwell_emphasis": "none"},
                run_time=0.8,
            ),
            words=wide[:3],
        ),
        BenchmarkCase(
            id="paged_slide",
            title="Two pages with slide transition; second wait must still fire",
            spec=_spec(
                "paged_slide",
                [],
                layout={"page_transition": "slide", "page_transition_run_time": 0.4},
                pages=[
                    {
                        "rows": [
                            {"run_time": 0.6, "boxes": [_box("Alpha", wait_word=0)]}
                        ]
                    },
                    {
                        "transition": "slide",
                        "rows": [
                            {"run_time": 0.6, "boxes": [_box("Beta", wait_word=1)]}
                        ],
                    },
                ],
            ),
            words=[
                {"word": "Alpha", "start": 1.2, "end": 1.4},
                {"word": "Beta", "start": 6.0, "end": 6.3},
                {"word": "tail", "start": 10.0, "end": 10.4},
            ],
        ),
        BenchmarkCase(
            id="flow_edges",
            title="Pipeline: first node grows, edge-to-edge arrow, paced holds",
            spec=_spec(
                "flow_edges",
                [
                    _box("Hints", wait_word=0, reveal="grow"),
                    _box("YAML", wait_word=1, color="C_BLUE"),
                ],
                edges=[{"from": "Hints", "to": "YAML", "color": "C_ACCENT"}],
                run_time=0.7,
            ),
            words=[
                {"word": "Hints", "start": 1.5, "end": 1.8},
                {"word": "YAML", "start": 7.0, "end": 7.3},
                {"word": "tail", "start": 12.0, "end": 12.4},
            ],
        ),
        BenchmarkCase(
            id="audio_tail",
            title="Last box holds through a long audio tail",
            spec=_spec("audio_tail", [_box("Alpha", wait_word=0)], run_time=0.6),
            words=[
                {"word": "Alpha", "start": 1.2, "end": 1.5},
                {"word": "tail", "start": 18.0, "end": 18.5},
            ],
        ),
    ]


def score_case(case: BenchmarkCase) -> CaseScore:
    words = case.words
    compile_words = words if case.compile_with_words else None
    src = compile_scene_class(case.spec, words=compile_words)
    trace: ClockTrace = run_compiled_scene_clock(src, words)
    audio_end = float(audio_end_from_words(words) or 0.0)
    issues = clock_contract_violations(trace, words, audio_end=audio_end)
    sim = simulate_reveal_timeline(case.spec, words, clamp_run_times=case.compile_with_words)
    drift = simulator_exec_drift_violations(sim, trace)
    cadence = reveal_cadence_violations(sim, audio_end=audio_end)
    idle = hold_idle_violations(sim, audio_end=audio_end)
    overshoots = sum(1 for msg in issues if msg.startswith("overshoot:"))
    last_motion = 0.0
    for ev in trace.play_events():
        if not ev.anim_kinds or "FadeOut" in ev.anim_kinds:
            continue
        last_motion = max(last_motion, ev.clock_after)
    frac = (last_motion / audio_end) if audio_end > 0 else 0.0
    wait_skips = len(trace.skipped_waits())
    defect_points = (
        15 * wait_skips
        + 15 * overshoots
        + 10 * len(idle)
        + 10 * len(cadence)
        + 10 * len(drift)
    )
    quality_points = 0
    if case.role == "quality":
        quality_points = min(12, len(trace.emphasis_plays()) * 2) + min(
            8, int(round(min(frac, 1.0) * 8))
        )
    score = max(0, min(100, 100 - defect_points + quality_points))
    return CaseScore(
        case_id=case.id,
        title=case.title,
        role=case.role,
        wait_skips=wait_skips,
        overshoots=overshoots,
        hold_idle_violations=len(idle),
        cadence_violations=len(cadence),
        sim_drift=len(drift),
        mid_hold_pulses=len(trace.emphasis_plays()),
        box_reveals=len(trace.reveal_plays()),
        last_motion_frac=frac,
        audio_end=audio_end,
        defect_points=defect_points,
        quality_points=quality_points,
        score=score,
        issues=issues + [f"drift: {m}" for m in drift] + cadence + idle,
    )


def run_benchmark(
    *,
    case_id: str | None = None,
) -> list[CaseScore]:
    cases = standard_cases()
    if case_id:
        cases = [c for c in cases if c.id == case_id]
        if not cases:
            known = ", ".join(c.id for c in standard_cases())
            raise ValueError(f"unknown benchmark case {case_id!r}; known: {known}")
    return [score_case(c) for c in cases]


def load_baseline(path: Path | None = None) -> dict[str, Any]:
    p = path or default_baseline_path()
    if not p.is_file():
        return {"version": 1, "cases": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def dump_baseline(scores: list[CaseScore]) -> dict[str, Any]:
    return {
        "version": 1,
        "cases": {s.case_id: s.snapshot() for s in scores},
    }


def write_baseline(scores: list[CaseScore], path: Path | None = None) -> Path:
    p = path or default_baseline_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dump_baseline(scores), indent=2) + "\n", encoding="utf-8")
    return p


def compare_to_baseline(
    scores: list[CaseScore],
    baseline: dict[str, Any],
) -> list[str]:
    """Return regression notes. Empty means the run meets or beats the baseline."""
    notes: list[str] = []
    stored = baseline.get("cases") if isinstance(baseline.get("cases"), dict) else {}
    for score in scores:
        prev = stored.get(score.case_id)
        if not isinstance(prev, dict):
            notes.append(f"{score.case_id}: missing from baseline (run --update-baseline)")
            continue
        if score.role == "control":
            prev_defects = int(prev.get("defect_points", 0))
            if score.defect_points <= 0:
                notes.append(
                    f"{score.case_id}: control no longer fails — scorer may be blind "
                    "to the historical dump"
                )
            elif score.defect_points < prev_defects // 2 and prev_defects >= 20:
                notes.append(
                    f"{score.case_id}: control defects dropped sharply "
                    f"({prev_defects} → {score.defect_points}); confirm this is intended"
                )
            continue
        if score.defect_points > int(prev.get("defect_points", 0)):
            notes.append(
                f"{score.case_id}: defect_points {prev.get('defect_points')} → "
                f"{score.defect_points} (regression)"
            )
        if score.quality_points < int(prev.get("quality_points", 0)):
            notes.append(
                f"{score.case_id}: quality_points {prev.get('quality_points')} → "
                f"{score.quality_points} (worse motion / tail coverage)"
            )
        if score.score < int(prev.get("score", 0)):
            notes.append(
                f"{score.case_id}: score {prev.get('score')} → {score.score}"
            )
        if score.wait_skips > int(prev.get("wait_skips", 0)):
            notes.append(
                f"{score.case_id}: wait_skips {prev.get('wait_skips')} → {score.wait_skips}"
            )
        if score.mid_hold_pulses < int(prev.get("mid_hold_pulses", 0)):
            notes.append(
                f"{score.case_id}: mid_hold_pulses {prev.get('mid_hold_pulses')} → "
                f"{score.mid_hold_pulses} (holds look more stuck)"
            )
    return notes


def format_table(scores: list[CaseScore]) -> str:
    headers = (
        f"{'case':<26} {'role':<8} {'skip':>4} {'ovr':>4} {'idle':>4} "
        f"{'drift':>5} {'pulse':>5} {'q':>3} {'def':>4} {'score':>5}"
    )
    lines = [headers, "-" * len(headers)]
    for s in scores:
        lines.append(
            f"{s.case_id:<26} {s.role:<8} {s.wait_skips:>4} {s.overshoots:>4} "
            f"{s.hold_idle_violations:>4} {s.sim_drift:>5} {s.mid_hold_pulses:>5} "
            f"{s.quality_points:>3} {s.defect_points:>4} {s.score:>5}"
        )
    quality = [s for s in scores if s.role == "quality"]
    if quality:
        avg = sum(s.score for s in quality) / len(quality)
        lines.append("-" * len(headers))
        lines.append(f"{'quality average':<26} {'':<8} {'':>4} {'':>4} {'':>4} {'':>5} {'':>5} {'':>3} {'':>4} {avg:5.1f}")
    return "\n".join(lines)


def scores_as_json(scores: list[CaseScore], *, regressions: list[str]) -> dict[str, Any]:
    return {
        "cases": [asdict(s) for s in scores],
        "quality_average": (
            sum(s.score for s in scores if s.role == "quality")
            / max(1, sum(1 for s in scores if s.role == "quality"))
        ),
        "regressions": regressions,
    }
