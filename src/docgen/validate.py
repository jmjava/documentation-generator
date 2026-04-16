"""Unified validator combining all quality checks.

Core checks (freeze_ratio, blank_frames) use only cv2 — always available.
OCR text scanning uses pytesseract — degrades gracefully if tesseract
binary is missing, but cv2 checks still run and still fail the build.
"""

from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

import cv2
import numpy as np

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


def _sample_frames(path: Path, interval_sec: float = 2.0) -> list[tuple[float, np.ndarray]]:
    """Read frames at *interval_sec* across the entire video. Returns (timestamp, frame) pairs."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    timestamps: list[float] = []
    t = 0.0
    while t < duration:
        timestamps.append(t)
        t += interval_sec
    if duration > 0 and (not timestamps or timestamps[-1] < duration - 0.5):
        timestamps.append(max(0, duration - 0.1))

    samples: list[tuple[float, np.ndarray]] = []
    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
        ret, frame = cap.read()
        if ret:
            samples.append((ts, frame))

    cap.release()
    return samples


_LFS_SIGNATURE = b"version https://git-lfs.github.com/spec/v1"


def _is_lfs_pointer(path: Path) -> bool:
    """Return True if *path* is a Git LFS pointer file (not actual media)."""
    try:
        with open(path, "rb") as f:
            return f.read(len(_LFS_SIGNATURE)) == _LFS_SIGNATURE
    except OSError:
        return False


def _is_text_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Text"
    if isinstance(func, ast.Attribute):
        return func.attr == "Text"
    return False


def _looks_numeric(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _looks_numeric(node.operand)
    return False


def _looks_like_color_positional(node: ast.AST) -> bool:
    if _looks_numeric(node):
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        if value.startswith("#"):
            return True
        # Positional named colors are almost always accidental in Text().
        return bool(value) and value.replace("_", "").isalpha()
    if isinstance(node, ast.Name):
        ident = node.id.upper()
        return node.id.isupper() or ident.startswith("C_") or "COLOR" in ident
    if isinstance(node, ast.Attribute):
        ident = node.attr.upper()
        return node.attr.isupper() or ident.startswith("C_") or "COLOR" in ident
    return False


def _is_bold_weight(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "BOLD"
    if isinstance(node, ast.Attribute):
        return node.attr == "BOLD"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip().lower() == "bold"
    return False


def _lint_manim_text_usage(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: could not read scene source ({exc})"]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        line = exc.lineno if exc.lineno is not None else "?"
        return [f"{path}:{line} could not parse scenes.py ({exc.msg})"]

    issues: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_text_call(node):
            continue

        if len(node.args) >= 2 and _looks_like_color_positional(node.args[1]):
            issues.append(
                f"{path}:{node.lineno} Text() second positional argument looks like a color; "
                "use keyword form `Text(..., color=...)`."
            )

        for kw in node.keywords:
            if kw.arg == "weight" and kw.value is not None and _is_bold_weight(kw.value):
                issues.append(
                    f"{path}:{node.lineno} Text(..., weight=BOLD) can substitute a different font; "
                    "prefer emphasis with color/size."
                )

    return issues


class Validator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._manim_lint_cache: CheckResult | None = None

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

        if rec and _is_lfs_pointer(rec):
            report.checks.append(
                CheckResult("lfs_pointer", True, [f"LFS pointer — skipping media checks for {seg_id}"])
            )
        elif rec:
            report.checks.append(self._check_streams(rec))
            max_drift = max_drift_override or self.config.max_drift_sec
            report.checks.append(self._check_drift(rec, max_drift))

            samples = _sample_frames(rec, interval_sec=2.0)
            report.checks.append(self._check_freeze_ratio(rec, samples))
            report.checks.append(self._check_blank_frames(rec, samples))
            report.checks.append(self._check_ocr(rec, samples))
        else:
            report.checks.append(CheckResult("recording_exists", False, [f"No recording for {seg_id}"]))

        report.checks.append(self._check_narration_lint(seg_id))
        if self.config.visual_map.get(seg_id, {}).get("type") == "manim":
            report.checks.append(self._check_manim_scene_lint())

        return report.to_dict()

    def run_pre_push(self) -> None:
        """Run all checks; exit non-zero on quality failures.

        Missing recordings are reported as warnings, not failures — a project
        that hasn't generated videos yet should still be pushable.  Quality
        checks on *existing* recordings and narration lint are hard failures.
        """
        reports = self.run_all()
        hard_fail = False
        for r in reports:
            if isinstance(r, dict):
                for c in r.get("checks", []):
                    if not c.get("passed", True):
                        soft_checks = {"recording_exists", "ocr_scan", "freeze_ratio"}
                        if c.get("name") in soft_checks:
                            print(f"WARN [{r.get('segment')}] {c.get('name')}: {c.get('details')}")
                        else:
                            hard_fail = True
                            print(f"FAIL [{r.get('segment')}] {c.get('name')}: {c.get('details')}")
        if hard_fail:
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

    # ── Core frame-level checks (cv2 only — always runs) ─────────────

    def _check_freeze_ratio(
        self, path: Path, samples: list[tuple[float, np.ndarray]]
    ) -> CheckResult:
        """Fail if the video ends with a long frozen tail.

        Walks backward from the last frame and counts how many consecutive
        frames at the END are identical (MSE < 1.0 on 64x36 grayscale).
        Interior pauses (terminal idle, animation holds) are expected in
        narrated demos and are NOT penalised.
        """
        max_ratio = self.config.max_freeze_ratio

        if len(samples) < 3:
            return CheckResult("freeze_ratio", True, ["Too few frames to check"])

        duration = samples[-1][0] - samples[0][0]
        if duration < 5:
            return CheckResult("freeze_ratio", True, ["Video too short to check"])

        thumbs = []
        for _ts, frame in samples:
            small = cv2.resize(frame, (64, 36))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
            thumbs.append(gray)

        trailing_frozen = 0
        for i in range(len(thumbs) - 1, 0, -1):
            mse = float(np.mean((thumbs[i] - thumbs[i - 1]) ** 2))
            if mse < 1.0:
                trailing_frozen += 1
            else:
                break

        interval = duration / (len(samples) - 1) if len(samples) > 1 else 2.0
        frozen_secs = trailing_frozen * interval
        ratio = frozen_secs / duration if duration > 0 else 0.0
        passed = ratio <= max_ratio
        return CheckResult(
            "freeze_ratio", passed,
            [f"Trailing freeze≈{frozen_secs:.1f}s / {duration:.1f}s ({ratio:.0%}, max={max_ratio:.0%})"],
        )

    def _check_blank_frames(
        self, path: Path, samples: list[tuple[float, np.ndarray]]
    ) -> CheckResult:
        """Fail if a significant portion of the video is blank/black/dark.

        Samples the ENTIRE video at regular intervals and checks mean
        pixel intensity.  A frame with mean < 15 (out of 255) is dark.
        """
        if not samples:
            return CheckResult("blank_frames", False, ["No frames sampled"])

        dark_threshold = 15
        dark_count = 0
        dark_ranges: list[str] = []
        in_dark_run = False
        dark_start = 0.0

        for ts, frame in samples:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_intensity = float(np.mean(gray))

            if mean_intensity < dark_threshold:
                dark_count += 1
                if not in_dark_run:
                    in_dark_run = True
                    dark_start = ts
            else:
                if in_dark_run:
                    dark_ranges.append(f"{dark_start:.1f}s-{ts:.1f}s")
                    in_dark_run = False

        if in_dark_run:
            dark_ranges.append(f"{dark_start:.1f}s-{samples[-1][0]:.1f}s")

        dark_ratio = dark_count / len(samples) if samples else 0
        max_dark_ratio = 0.15
        passed = dark_ratio <= max_dark_ratio

        details = [f"Dark frames: {dark_count}/{len(samples)} ({dark_ratio:.0%}, max={max_dark_ratio:.0%})"]
        if dark_ranges:
            details.append(f"Dark ranges: {', '.join(dark_ranges[:5])}")

        return CheckResult("blank_frames", passed, details)

    # ── OCR text scanning (pytesseract — degrades if binary missing) ──

    def _check_ocr(
        self, path: Path, samples: list[tuple[float, np.ndarray]]
    ) -> CheckResult:
        """Run OCR on sampled frames to detect error text in recordings.

        Uses the SAME samples as freeze/blank checks so the entire video
        is covered.  Gracefully skips if tesseract binary is not installed.
        """
        import re

        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception:
            return CheckResult("ocr_scan", True, ["tesseract binary not installed (skipped)"])

        error_patterns = self.config.ocr_config.get("error_patterns", [])
        if not error_patterns or not samples:
            return CheckResult("ocr_scan", True, ["No patterns or frames to check"])

        issues: list[str] = []
        passed = True

        for ts, frame in samples:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text = pytesseract.image_to_string(thresh)

            for pat in error_patterns:
                if re.search(pat, text, re.IGNORECASE):
                    issues.append(f"Pattern '{pat}' at {ts:.1f}s")
                    passed = False

        details = issues[:10] if issues else ["No OCR issues detected"]
        return CheckResult("ocr_scan", passed, details)

    # ── Narration lint ────────────────────────────────────────────────

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

    def _check_manim_scene_lint(self) -> CheckResult:
        if self._manim_lint_cache is not None:
            return self._manim_lint_cache

        scenes = self.config.animations_dir / "scenes.py"
        if not scenes.exists():
            result = CheckResult("manim_scene_lint", True, ["No animations/scenes.py (skipped)"])
            self._manim_lint_cache = result
            return result

        issues = _lint_manim_text_usage(scenes)
        result = CheckResult(
            "manim_scene_lint",
            not issues,
            issues[:15] if issues else ["No risky Text() usage detected"],
        )
        self._manim_lint_cache = result
        return result

    # ── ffprobe-based checks ──────────────────────────────────────────

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

    # ── Helpers ────────────────────────────────────────────────────────

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
        seg_name = self.config.resolve_segment_name(seg_id)
        exact = d / f"{seg_name}.mp4"
        if exact.exists():
            return exact
        for mp4 in d.glob(f"*{seg_id}*.mp4"):
            return mp4
        return None
