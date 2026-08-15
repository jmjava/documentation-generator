"""Standard scene-timing benchmark: executed clock, not source-string checks."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from docgen.cli import main
from docgen.scene_benchmark import (
    compare_to_baseline,
    default_baseline_path,
    format_table,
    load_baseline,
    run_benchmark,
    score_case,
    standard_cases,
)
from docgen.scene_clock_harness import run_compiled_scene_clock
from docgen.scene_spec import compile_scene_class


def test_corpus_ids_are_stable() -> None:
    ids = [c.id for c in standard_cases()]
    assert ids == [
        "issue66_tight_clamped",
        "issue66_tight_unclamped",
        "early_title",
        "wide_hold",
        "emphasis_none",
        "paged_slide",
        "flow_edges",
        "audio_tail",
    ]


def test_control_case_still_detects_issue66_dump() -> None:
    case = next(c for c in standard_cases() if c.id == "issue66_tight_unclamped")
    score = score_case(case)
    assert score.role == "control"
    assert score.wait_skips >= 2
    assert score.defect_points > 0
    assert any("no-op" in i for i in score.issues)


def test_clamped_issue66_case_does_not_skip_waits() -> None:
    case = next(c for c in standard_cases() if c.id == "issue66_tight_clamped")
    score = score_case(case)
    assert score.wait_skips == 0
    assert score.overshoots == 0
    assert score.defect_points == 0


def test_harness_runs_real_timed_scene_clock() -> None:
    case = next(c for c in standard_cases() if c.id == "early_title")
    src = compile_scene_class(case.spec, words=case.words)
    trace = run_compiled_scene_clock(src, case.words)
    waits = trace.wait_word_events()
    assert waits
    assert not any(w.skipped for w in waits)
    # First spoken start is 0.55s; an unclamped 1.0s title Write would skip it.
    assert waits[0].word_start == 0.55
    assert waits[0].clock_before <= 0.55 + 0.02


def test_wide_hold_executes_more_than_one_pulse() -> None:
    case = next(c for c in standard_cases() if c.id == "wide_hold")
    score = score_case(case)
    assert score.mid_hold_pulses >= 2
    assert score.wait_skips == 0


def test_emphasis_none_emits_no_pulses() -> None:
    case = next(c for c in standard_cases() if c.id == "emphasis_none")
    score = score_case(case)
    assert score.mid_hold_pulses == 0
    assert score.wait_skips == 0


def test_full_corpus_meets_committed_baseline() -> None:
    scores = run_benchmark()
    baseline = load_baseline()
    assert baseline.get("cases"), "baseline.json is missing — run docgen benchmark --update-baseline"
    notes = compare_to_baseline(scores, baseline)
    assert notes == [], "\n".join(notes)
    table = format_table(scores)
    assert "issue66_tight_clamped" in table
    assert "quality average" in table


def test_compare_flags_skip_regression() -> None:
    scores = run_benchmark()
    dump = load_baseline()
    cases = dict(dump["cases"])
    cases["issue66_tight_clamped"] = {
        **cases["issue66_tight_clamped"],
        "wait_skips": 0,
        "defect_points": 0,
        "score": 100,
    }
    # Pretend baseline was perfect; inject a worse score object.
    worse = next(s for s in scores if s.case_id == "issue66_tight_clamped")
    worse.wait_skips = 2
    worse.defect_points = 30
    worse.score = 70
    notes = compare_to_baseline([worse], {"version": 1, "cases": cases})
    assert notes
    assert any("wait_skips" in n or "defect_points" in n or "score" in n for n in notes)


def test_cli_benchmark_text_and_json(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["benchmark", "--format", "text"])
    assert result.exit_code == 0, result.output
    assert "issue66_tight_clamped" in result.output
    out = tmp_path / "report.json"
    result = runner.invoke(
        main,
        ["benchmark", "--format", "json", "--output", str(out), "--case", "early_title"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["cases"][0]["case_id"] == "early_title"


def test_packaged_baseline_exists() -> None:
    path = default_baseline_path()
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["cases"]) == {c.id for c in standard_cases()}


def test_cli_registers_benchmark_command() -> None:
    assert "benchmark" in main.commands


def test_ci_workflow_requires_docgen_benchmark() -> None:
    """Future PRs must not drop the named CI job that runs the corpus."""
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "\n  benchmark:" in text
    assert "docgen benchmark" in text
    assert "Scene-timing benchmark" in text


def test_agent_rules_require_benchmark() -> None:
    root = Path(__file__).resolve().parents[1]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Required gate: `docgen benchmark`" in agents
    rule = (root / ".cursor" / "rules" / "docgen-benchmark.mdc").read_text(encoding="utf-8")
    assert "docgen benchmark" in rule
    assert "alwaysApply: true" in rule
