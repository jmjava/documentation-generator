"""Validator extensions for visual_map type playwright_test."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.validate import Validator


def _write_matching_events(rendered: Path) -> None:
    events = [
        {"t": 0.0, "action": "goto", "url": "/"},
        {"t": 1.0, "action": "click", "selector": "button"},
    ]
    (rendered / "03-demo_events.json").write_text(json.dumps(events), encoding="utf-8")


@pytest.fixture
def pw_base(tmp_path: Path) -> Path:
    cfg = {
        "segments": {"default": ["03"], "all": ["03"]},
        "segment_names": {"03": "03-demo"},
        "visual_map": {
            "03": {
                "type": "playwright_test",
                "test": "tests/e2e/test_demo.py::test_flow",
                "source": "videos/demo.webm",
                "trace": "traces/demo/trace.zip",
                "anchors": [
                    {"narration_anchor": "open app", "action": "goto"},
                    {"narration_anchor": "click run", "action": "click"},
                ],
            },
        },
        "validation": {"max_drift_sec": 2.75},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    rendered = tmp_path / "terminal" / "rendered"
    rendered.mkdir(parents=True)
    _write_matching_events(rendered)
    return tmp_path


def test_playwright_context_lists_test_and_paths(pw_base: Path) -> None:
    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    names = [c["name"] for c in report["checks"]]
    assert "playwright_test_context" in names
    ctx = next(c for c in report["checks"] if c["name"] == "playwright_test_context")
    joined = " ".join(ctx["details"])
    assert "tests/e2e/test_demo.py::test_flow" in joined
    assert "demo.webm" in joined


def test_playwright_events_alignment_passes_when_counts_match(pw_base: Path) -> None:
    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    ev = next(c for c in report["checks"] if c["name"] == "playwright_test_events")
    assert ev["passed"] is True


def test_playwright_events_alignment_fails_on_mismatch(pw_base: Path) -> None:
    rendered = pw_base / "terminal" / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    events = [{"t": 0.0, "action": "goto", "url": "/"}]
    (rendered / "03-demo_events.json").write_text(json.dumps(events), encoding="utf-8")

    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    ev = next(c for c in report["checks"] if c["name"] == "playwright_test_events")
    assert ev["passed"] is False


def test_playwright_trace_fails_on_test_status(pw_base: Path) -> None:
    rendered = pw_base / "terminal" / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_status": "failed",
        "error": "Timeout 5000ms exceeded",
        "events": [
            {"t": 0.0, "action": "goto", "url": "/"},
            {"t": 1.0, "action": "click", "selector": "button"},
        ],
    }
    (rendered / "03-demo_events.json").write_text(json.dumps(payload), encoding="utf-8")

    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    tr = next(c for c in report["checks"] if c["name"] == "playwright_test_trace")
    assert tr["passed"] is False


def test_playwright_speed_warns_outside_config_bounds(pw_base: Path) -> None:
    rendered = pw_base / "terminal" / "rendered"
    sync = {
        "speed_segments": [
            {"start": 0.0, "end": 1.0, "factor": 1.0},
            {"start": 1.0, "end": 3.0, "factor": 8.0},
        ],
    }
    (rendered / "03-demo_sync_map.json").write_text(json.dumps(sync), encoding="utf-8")

    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    sp = next(c for c in report["checks"] if c["name"] == "playwright_test_speed")
    assert sp["passed"] is True
    assert any("WARN" in d for d in sp["details"])


def test_playwright_sync_duration_passes_when_anchor_within_audio(
    pw_base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = pw_base / "terminal" / "rendered"
    audio = pw_base / "audio"
    audio.mkdir(parents=True)
    sync = {"anchors": [{"event_t": 0.0, "narration_t": 1.0, "action": "goto"}]}
    (rendered / "03-demo_sync_map.json").write_text(json.dumps(sync), encoding="utf-8")
    (audio / "03-demo.mp3").write_bytes(b"fake")

    def fake_probe(_path: Path) -> float | None:
        return 10.0

    monkeypatch.setattr(Validator, "_ffprobe_duration", staticmethod(fake_probe))

    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    sd = next(c for c in report["checks"] if c["name"] == "playwright_test_sync_duration")
    assert sd["passed"] is True


def test_playwright_trace_zip_fatal_error(pw_base: Path) -> None:
    # Default events file is a plain array (no test_status); trace zip is scanned next.
    trace_dir = pw_base / "traces" / "demo"
    trace_dir.mkdir(parents=True)
    zpath = trace_dir / "trace.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("0-manifest.json", '{"fatalError":"boom"}')

    cfg = Config.from_yaml(pw_base)
    v = Validator(cfg)
    report = v.validate_segment("03")
    tr = next(c for c in report["checks"] if c["name"] == "playwright_test_trace")
    assert tr["passed"] is False
