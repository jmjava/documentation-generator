"""Unified validator combining all quality checks."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    segment: str | None = None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "details": c.details}
                for c in self.checks
            ],
        }


class Validator:
    def __init__(self, config: Config) -> None:
        self.config = config

    def run_all(self, max_drift_override: float | None = None) -> list[ValidationReport]:
        reports: list[ValidationReport] = []
        for seg_id in self.config.segments_all:
            reports.append(self.validate_segment(seg_id, max_drift_override))
        return reports

    def validate_segment(
        self, seg_id: str, max_drift_override: float | None = None
    ) -> dict[str, Any]:
        report = ValidationReport(segment=seg_id)
        rec = self._find_recording(seg_id)

        if rec:
            report.checks.append(self._check_streams(rec))
            max_drift = max_drift_override or self.config.max_drift_sec
            report.checks.append(self._check_drift(rec, max_drift))
        else:
            report.checks.append(CheckResult("recording_exists", False, [f"No recording for {seg_id}"]))

        report.checks.append(self._check_narration_lint(seg_id))

        return report.to_dict()

    def run_pre_push(self) -> None:
        reports = self.run_all()
        all_passed = True
        for r in reports:
            if isinstance(r, dict):
                for c in r.get("checks", []):
                    if not c.get("passed", True):
                        all_passed = False
                        print(f"FAIL [{r.get('segment')}] {c.get('name')}: {c.get('details')}")
        if not all_passed:
            raise SystemExit(1)
        print("[validate] All checks passed")

    def print_report(self, reports: list) -> None:
        for r in reports:
            if isinstance(r, dict):
                seg = r.get("segment", "?")
                for c in r.get("checks", []):
                    status = "PASS" if c.get("passed") else "FAIL"
                    print(f"  [{seg}] {status} {c.get('name')}")
                    for d in c.get("details", []):
                        print(f"    {d}")

    def _check_narration_lint(self, seg_id: str) -> CheckResult:
        narr = self._find_narration(seg_id)
        if not narr:
            return CheckResult("narration_lint", True, ["No narration file (skipped)"])
        from docgen.narration_lint import lint_pre_tts
        text = narr.read_text(encoding="utf-8")
        deny = self.config.narration_lint_config.get("pre_tts_deny_patterns")
        result = lint_pre_tts(text, deny_patterns=deny)
        return CheckResult(
            "narration_lint",
            result.passed,
            result.issues[:10] if result.issues else [],
        )

    def _find_narration(self, seg_id: str) -> Path | None:
        d = self.config.narration_dir
        if not d.exists():
            return None
        seg_name = self.config.resolve_segment_name(seg_id)
        exact = d / f"{seg_name}.md"
        if exact.exists():
            return exact
        for md in d.glob(f"{seg_id}-*.md"):
            return md
        for md in d.glob(f"*{seg_id}*.md"):
            return md
        return None

    def _find_recording(self, seg_id: str) -> Path | None:
        d = self.config.recordings_dir
        if not d.exists():
            return None
        for mp4 in d.glob(f"*{seg_id}*.mp4"):
            return mp4
        return None

    def _check_streams(self, path: Path) -> CheckResult:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            data = json.loads(out.stdout)
            streams = data.get("streams", [])
            has_video = any(s.get("codec_type") == "video" for s in streams)
            has_audio = any(s.get("codec_type") == "audio" for s in streams)
            issues = []
            if not has_video:
                issues.append("Missing video stream")
            if not has_audio:
                issues.append("Missing audio stream")
            return CheckResult("stream_presence", has_video and has_audio, issues)
        except Exception as exc:
            return CheckResult("stream_presence", False, [str(exc)])

    def _check_drift(self, path: Path, max_drift: float) -> CheckResult:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            data = json.loads(out.stdout)
            durations: dict[str, float] = {}
            for s in data.get("streams", []):
                ct = s.get("codec_type", "")
                dur = float(s.get("duration", 0))
                if ct in ("video", "audio") and dur > 0:
                    durations[ct] = dur

            if "video" not in durations or "audio" not in durations:
                return CheckResult("av_drift", False, ["Cannot determine both stream durations"])

            drift = abs(durations["video"] - durations["audio"])
            passed = drift <= max_drift
            return CheckResult(
                "av_drift", passed,
                [f"Video={durations['video']:.2f}s Audio={durations['audio']:.2f}s Drift={drift:.2f}s (max={max_drift})"],
            )
        except Exception as exc:
            return CheckResult("av_drift", False, [str(exc)])
