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


def _extract_font_size(node: ast.Call) -> int | None:
    """Return the font_size value from a Text() call, or None if absent/dynamic."""
    for kw in node.keywords:
        if kw.arg == "font_size" and isinstance(kw.value, ast.Constant):
            val = kw.value.value
            if isinstance(val, (int, float)):
                return int(val)
    return None


def _ast_is_double_self_clock_tuple(node: ast.expr) -> bool:
    """True for ``(self._clock, self._clock)`` / ``self._clock, self._clock`` tuple pairs."""
    if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
        return False

    def is_clock(e: ast.expr) -> bool:
        return (
            isinstance(e, ast.Attribute)
            and e.attr == "_clock"
            and isinstance(e.value, ast.Name)
            and e.value.id == "self"
        )

    return is_clock(node.elts[0]) and is_clock(node.elts[1])


def lint_manim_timing_stub_antipattern(tree: ast.AST, path_label: str) -> list[str]:
    """Reject a known-bad LLM pattern that assigns ``seg_*`` from ``self._clock`` then calls them.

    That code raises at runtime (calling a float). Fix: regenerate with
    ``docgen scene-spec-generate`` / ``scene-compile`` or replace with explicit
    ``timed_play`` ``run_time``.
    """
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("seg_start", "seg_end"):
                issues.append(
                    f"{path_label}:{node.lineno} invalid call {node.func.id}(...) — "
                    "broken timing placeholder; run `docgen scene-spec-generate --segment …` "
                    "(or `scene-compile` from a saved spec) to regenerate this scene, "
                    "or use only `timed_play(..., run_time=...)`."
                )
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Tuple) and len(tgt.elts) == 2:
                a, b = tgt.elts
                if (
                    isinstance(a, ast.Name)
                    and isinstance(b, ast.Name)
                    and a.id == "seg_start"
                    and b.id == "seg_end"
                    and _ast_is_double_self_clock_tuple(node.value)
                ):
                    issues.append(
                        f"{path_label}:{node.lineno} invalid "
                        "`seg_start, seg_end = self._clock, self._clock` — "
                        "breaks Manim at runtime; regenerate with `docgen scene-spec-generate` / "
                        "`scene-compile`."
                    )
    return issues


def _lint_manim_text_usage(
    path: Path,
    *,
    min_font_size: int = 14,
    unsafe_unicode: list[str] | None = None,
) -> list[str]:
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

    if unsafe_unicode:
        for lineno, line_text in enumerate(source.splitlines(), start=1):
            for ch in unsafe_unicode:
                if ch in line_text:
                    issues.append(
                        f"{path}:{lineno} Unsafe unicode character U+{ord(ch):04X} "
                        f"({repr(ch)}) may trigger Pango font fallback; "
                        "use an ASCII equivalent."
                    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_text_call(node):
            continue

        if len(node.args) >= 2 and _looks_like_color_positional(node.args[1]):
            issues.append(
                f"{path}:{node.lineno} Text() second positional argument looks like a color; "
                "use keyword form `Text(..., color=...)`."
            )

        kw_names = {kw.arg for kw in node.keywords if kw.arg}
        if "font" not in kw_names:
            issues.append(
                f"{path}:{node.lineno} Text() is missing font=MANIM_FONT; "
                "machine Pango defaults drift (font consistency)."
            )

        for kw in node.keywords:
            if kw.arg == "weight" and kw.value is not None and _is_bold_weight(kw.value):
                issues.append(
                    f"{path}:{node.lineno} Text(..., weight=BOLD) can substitute a different font; "
                    "prefer emphasis with color/size."
                )

        font_size = _extract_font_size(node)
        if font_size is not None and font_size < min_font_size:
            issues.append(
                f"{path}:{node.lineno} Text() font_size={font_size} is below minimum {min_font_size}; "
                "small text is unreadable in video."
            )

    issues.extend(lint_manim_timing_stub_antipattern(tree, str(path)))

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
        max_drift = max_drift_override or self.config.max_drift_sec
        rec = self._find_recording(seg_id)

        if rec and _is_lfs_pointer(rec):
            report.checks.append(
                CheckResult("lfs_pointer", True, [f"LFS pointer — skipping media checks for {seg_id}"])
            )
        elif rec:
            vmap0 = self.config.visual_map.get(seg_id, {})
            vt0 = vmap0.get("type") if isinstance(vmap0, dict) else None
            report.checks.append(self._check_streams(rec))
            report.checks.append(self._check_drift(rec, max_drift))

            samples = _sample_frames(rec, interval_sec=2.0)
            report.checks.append(self._check_freeze_ratio(rec, samples, visual_type=vt0))
            report.checks.append(self._check_blank_frames(rec, samples))
            report.checks.append(self._check_ocr(rec, samples))

            vmap = self.config.visual_map.get(seg_id, {})
            if vmap.get("type") == "manim":
                report.checks.append(self._check_layout(rec))
            report.checks.append(self._check_av_sync(seg_id, rec))
        else:
            report.checks.append(CheckResult("recording_exists", False, [f"No recording for {seg_id}"]))

        report.checks.append(self._check_timing_sync(seg_id))
        report.checks.append(self._check_story_end(seg_id))
        report.checks.append(self._check_narration_lint(seg_id))
        if self.config.visual_map.get(seg_id, {}).get("type") == "manim":
            report.checks.append(self._check_manim_scene_lint())
            report.checks.append(self._check_subject_beat_coverage(seg_id))
            report.checks.append(self._check_scene_assets(seg_id))

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
                        soft_checks = {
                            "recording_exists",
                            "ocr_scan",
                            "freeze_ratio",
                            "layout",
                            # OCR keyword anchoring is heuristic; warn, don't block.
                            "av_sync",
                            # Subject-beat coverage is enforced hard at scene-spec-generate;
                            # on pre-push warn so shipping committed recordings is not blocked
                            # by a new heuristic gate mid-regeneration.
                            "subject_beat_coverage",
                        }
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
        self,
        path: Path,
        samples: list[tuple[float, np.ndarray]],
        *,
        visual_type: str | None = None,
    ) -> CheckResult:
        """Fail if the video ends with a long frozen tail.

        Walks backward from the last frame and counts how many consecutive
        frames at the END are identical (MSE < 1.0 on 64x36 grayscale).
        Interior pauses (mid-roll stillness, animation holds) are expected in
        narrated demos and are NOT penalised.
        """
        max_ratio = self.config.effective_max_freeze_ratio(visual_type)

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

        if not self.config.manim_scene_lint_enabled:
            result = CheckResult(
                "manim_scene_lint",
                True,
                ["manim.scene_lint disabled in config (skipped)"],
            )
            self._manim_lint_cache = result
            return result

        scenes = self.config.animations_dir / "scenes.py"
        if not scenes.exists():
            result = CheckResult("manim_scene_lint", True, ["No animations/scenes.py (skipped)"])
            self._manim_lint_cache = result
            return result

        issues = _lint_manim_text_usage(
            scenes,
            min_font_size=self.config.manim_min_font_size,
            unsafe_unicode=self.config.manim_unsafe_unicode,
        )
        result = CheckResult(
            "manim_scene_lint",
            not issues,
            issues[:15] if issues else ["No risky Text() usage detected"],
        )
        self._manim_lint_cache = result
        return result

    def _check_subject_beat_coverage(self, seg_id: str) -> CheckResult:
        """Ensure declarative scene YAML covers narration subject beats (not a blind count)."""
        if not self.config.subject_beat_coverage_enabled:
            return CheckResult(
                "subject_beat_coverage",
                True,
                ["validation.subject_beat_coverage disabled in config (skipped)"],
            )

        narr_path = self._find_narration(seg_id)
        if narr_path is None or not narr_path.is_file():
            return CheckResult(
                "subject_beat_coverage",
                True,
                ["No narration file (skipped)"],
            )

        seg_name = self.config.resolve_segment_name(seg_id)
        spec_path = self.config.animations_dir / "specs" / f"{seg_name}.scene.yaml"
        if not spec_path.is_file():
            return CheckResult(
                "subject_beat_coverage",
                True,
                [
                    f"No {spec_path.name} (skipped — hand-authored scenes.py "
                    "without declarative spec)"
                ],
            )

        import yaml

        from docgen.scene_spec import layout_density_violations

        try:
            raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return CheckResult(
                "subject_beat_coverage",
                False,
                [f"could not load {spec_path.name}: {exc}"],
            )
        if not isinstance(raw, dict):
            return CheckResult(
                "subject_beat_coverage",
                False,
                [f"{spec_path.name}: root must be a mapping"],
            )

        narration_text = narr_path.read_text(encoding="utf-8")
        issues = layout_density_violations(raw, narration_text=narration_text)
        if issues:
            return CheckResult("subject_beat_coverage", False, issues)
        return CheckResult(
            "subject_beat_coverage",
            True,
            ["Subject beats covered; no invented unspoken labels"],
        )

    def _check_scene_assets(self, seg_id: str) -> CheckResult:
        """Pre-render stuck / overlap / font / compile-sync gate (no video required)."""
        sa_cfg = self.config.scene_assets_config
        if not sa_cfg.get("enabled", True):
            return CheckResult(
                "scene_assets",
                True,
                ["validation.scene_assets disabled (skipped)"],
            )
        is_manim = self.config.visual_map.get(seg_id, {}).get("type") == "manim"
        if not is_manim:
            return CheckResult("scene_assets", True, ["non-manim (skipped)"])

        from docgen.scene_asset_validate import scene_asset_violations_for_segment

        issues = scene_asset_violations_for_segment(self.config, seg_id)
        if issues:
            return CheckResult("scene_assets", False, issues[:20])
        return CheckResult(
            "scene_assets",
            True,
            ["Spec layout, reveal cadence, helpers, and compiled class are consistent"],
        )

    def _check_layout(self, path: Path) -> CheckResult:
        """Run overlap/spacing/edge layout checks on a Manim video recording."""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception:
            return CheckResult("layout", True, ["tesseract not installed — layout check skipped"])

        try:
            from docgen.manim_layout import LayoutValidator
            lv = LayoutValidator(self.config)
            report = lv.validate_video(path)
            if report.passed:
                return CheckResult("layout", True, ["No layout issues detected"])
            details = [
                f"[{i.kind}] {i.description} at {i.timestamp_sec:.1f}s"
                for i in report.issues[:10]
            ]
            return CheckResult("layout", False, details)
        except Exception as exc:
            return CheckResult("layout", True, [f"Layout check error (skipped): {exc}"])

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
            issues: list[str] = []
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

            has_video_stream = any(
                s.get("codec_type") == "video" for s in data.get("streams", [])
            )
            fmt_dur_raw = data.get("format", {}).get("duration")
            if has_video_stream and "video" not in durations and fmt_dur_raw is not None:
                try:
                    fd = float(fmt_dur_raw)
                    if fd > 0:
                        durations["video"] = fd
                except (TypeError, ValueError):
                    pass

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

    # ── Audio ↔ timing.json sync ──────────────────────────────────────

    def _check_timing_sync(self, seg_id: str) -> CheckResult:
        """Detect stale ``timing.json`` relative to the TTS mp3 for this segment.

        Scenes pace themselves from Whisper word timestamps, so a re-generated
        mp3 with an old timing.json silently desyncs every reveal. Compares the
        mp3 duration against the last transcribed word/segment ``end``.
        """
        ts_cfg = self.config.timing_sync_config
        if not ts_cfg.get("enabled", True):
            return CheckResult("timing_sync", True, ["validation.timing_sync disabled (skipped)"])

        audio = self._find_audio(seg_id)
        if not audio:
            return CheckResult("timing_sync", True, [f"No audio for {seg_id} (skipped)"])
        if _is_lfs_pointer(audio):
            return CheckResult("timing_sync", True, ["Audio is an LFS pointer (skipped)"])

        is_manim = self.config.visual_map.get(seg_id, {}).get("type") == "manim"
        block = self._load_timing_block(seg_id)
        if block is None:
            if is_manim:
                return CheckResult(
                    "timing_sync",
                    False,
                    [
                        f"audio/{audio.name} exists but timing.json has no entry for "
                        f"{self.config.resolve_segment_name(seg_id)!r} — run `docgen timestamps`"
                    ],
                )
            return CheckResult("timing_sync", True, ["No timing.json entry (skipped, non-manim)"])

        last_end = self._timing_last_end(block)
        if last_end is None:
            if is_manim:
                return CheckResult(
                    "timing_sync",
                    False,
                    ["timing.json entry has no words/segments — re-run `docgen timestamps`"],
                )
            return CheckResult("timing_sync", True, ["Empty timing entry (skipped, non-manim)"])

        audio_dur = self._probe_media_duration(audio)
        if audio_dur is None:
            return CheckResult("timing_sync", True, ["Cannot probe audio duration (skipped)"])

        max_tail = float(ts_cfg.get("max_tail_gap_sec", 3.0))
        max_overrun = float(ts_cfg.get("max_end_overrun_sec", 1.0))
        detail = (
            f"Audio={audio_dur:.2f}s transcript_end={last_end:.2f}s "
            f"(max_tail_gap={max_tail}, max_end_overrun={max_overrun})"
        )
        if last_end > audio_dur + max_overrun:
            return CheckResult(
                "timing_sync",
                False,
                [
                    detail,
                    "timing.json extends past the audio — stale timestamps from a longer "
                    "take; run `docgen timestamps` (then `docgen manim` + `docgen compose`).",
                ],
            )
        if audio_dur - last_end > max_tail:
            return CheckResult(
                "timing_sync",
                False,
                [
                    detail,
                    "audio runs well past the last transcribed word — stale timestamps from "
                    "a shorter take; run `docgen timestamps` (then `docgen manim` + `docgen compose`).",
                ],
            )
        return CheckResult("timing_sync", True, [detail])

    def _check_story_end(self, seg_id: str) -> CheckResult:
        """Fail when the paced visual story finishes long before the narration ends.

        Muxed recordings can still match mp3 length (compose freezes the last frame)
        while the diagram finished early. Uses scene-spec label→``wait_word`` starts
        vs audio/transcript end. Hard fail in ``--pre-push`` (not soft like ``av_sync``).
        """
        se_cfg = self.config.story_end_config
        if not se_cfg.get("enabled", True):
            return CheckResult("story_end", True, ["validation.story_end disabled (skipped)"])

        is_manim = self.config.visual_map.get(seg_id, {}).get("type") == "manim"
        if not is_manim:
            return CheckResult("story_end", True, ["non-manim (skipped)"])

        from docgen.scene_retime import list_scene_spec_paths
        from docgen.scene_spec import last_paced_reveal_time, load_scene_spec

        paths = list_scene_spec_paths(self.config, segment_id=seg_id)
        if not paths:
            return CheckResult(
                "story_end", True, ["No animations/specs/*.scene.yaml (skipped)"]
            )

        block = self._load_timing_block(seg_id)
        if block is None:
            return CheckResult(
                "story_end",
                True,
                ["No timing.json entry (skipped) — run `docgen timestamps`"],
            )
        words = block.get("words")
        if not isinstance(words, list) or not words:
            return CheckResult(
                "story_end", True, ["No timing words (skipped)"]
            )

        last_reveal: float | None = None
        for path in paths:
            try:
                spec = load_scene_spec(path)
            except Exception as exc:
                return CheckResult(
                    "story_end",
                    False,
                    [f"Cannot load scene spec {path.name}: {exc}"],
                )
            t = last_paced_reveal_time(spec, words)
            if t is not None and (last_reveal is None or t > last_reveal):
                last_reveal = t

        if last_reveal is None:
            return CheckResult(
                "story_end",
                True,
                ["No paced reveals in scene spec (skipped)"],
            )

        audio = self._find_audio(seg_id)
        audio_end = self._probe_media_duration(audio) if audio and not _is_lfs_pointer(audio) else None
        transcript_end = self._timing_last_end(block)
        # Prefer audio duration; fall back to transcript end when probe fails.
        end_t = audio_end if audio_end is not None else transcript_end
        if end_t is None or end_t <= 0:
            return CheckResult("story_end", True, ["Cannot determine audio/transcript end (skipped)"])

        early_idle = end_t - last_reveal
        max_early_sec = float(se_cfg.get("max_early_sec", 40.0))
        max_early_ratio = float(se_cfg.get("max_early_ratio", 0.45))
        early_ratio = early_idle / end_t if end_t > 0 else 0.0
        detail = (
            f"last_paced_reveal={last_reveal:.2f}s audio_end={end_t:.2f}s "
            f"early_idle={early_idle:.2f}s ({early_ratio:.0%}) "
            f"(max_early_sec={max_early_sec}, max_early_ratio={max_early_ratio})"
        )
        if early_idle > max_early_sec and early_ratio > max_early_ratio:
            return CheckResult(
                "story_end",
                False,
                [
                    detail,
                    "Visual story finishes long before narration ends — boxes race then freeze. "
                    "Add paced labels for later narration beats, or run "
                    "`docgen scene-spec-generate` / `scene-compile --retime` after timestamps.",
                ],
            )
        return CheckResult("story_end", True, [detail])

    def _check_av_sync(self, seg_id: str, rec: Path) -> CheckResult:
        """OCR anchor check: spoken keywords should be visible on screen near their spoken time.

        Heuristic (soft in --pre-push). Uses ``timing.json`` — no network calls.
        Skips when tesseract is unavailable, timing data is missing, or the
        segment's visual type is not in ``validation.av_sync.visual_types``.
        """
        sync_cfg = self.config.av_sync_config
        if not sync_cfg.get("enabled", True):
            return CheckResult("av_sync", True, ["validation.av_sync disabled (skipped)"])

        vt = str(self.config.visual_map.get(seg_id, {}).get("type", "")).strip().lower()
        allowed = [str(t).strip().lower() for t in sync_cfg.get("visual_types", ["manim"])]
        if allowed and vt not in allowed:
            return CheckResult("av_sync", True, [f"visual type {vt!r} not checked (skipped)"])

        try:
            import pytesseract
            pytesseract.get_tesseract_version()
        except Exception:
            return CheckResult("av_sync", True, ["tesseract binary not installed (skipped)"])

        block = self._load_timing_block(seg_id)
        if block is None:
            return CheckResult(
                "av_sync", True, ["No timing.json entry (skipped) — run `docgen timestamps`"]
            )

        from docgen.av_sync import AVSyncValidator

        report = AVSyncValidator(self.config).validate_segment_with_timing(seg_id, rec, block)
        if report.passed:
            details = [f"{len(report.anchors)} anchor keyword(s) visible near spoken time"]
            return CheckResult("av_sync", True, details)
        missing = [a for a in report.anchors if not a.visible]
        details = [
            f"'{a.keyword}' spoken at {a.spoken_at:.1f}s but not found on screen "
            f"within ±{sync_cfg.get('tolerance_sec', 3.0)}s"
            for a in missing[:5]
        ]
        return CheckResult("av_sync", False, details)

    def _load_timing_block(self, seg_id: str) -> dict[str, Any] | None:
        """One segment's block from ``animations/timing.json`` (keyed by narration stem)."""
        timing_path = self.config.animations_dir / "timing.json"
        if not timing_path.is_file():
            return None
        try:
            data = json.loads(timing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        stem = self.config.resolve_segment_name(seg_id)
        block = data.get(stem)
        if not isinstance(block, dict):
            audio = self._find_audio(seg_id)
            if audio is not None:
                block = data.get(audio.stem)
        return block if isinstance(block, dict) else None

    @staticmethod
    def _timing_last_end(block: dict[str, Any]) -> float | None:
        """Latest ``end`` across words (preferred) then segments; None if neither exists."""
        for key in ("words", "segments"):
            entries = block.get(key)
            if isinstance(entries, list) and entries:
                ends: list[float] = []
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    try:
                        ends.append(float(e.get("end", 0.0)))
                    except (TypeError, ValueError):
                        continue
                if ends:
                    return max(ends)
        return None

    @staticmethod
    def _probe_media_duration(path: Path) -> float | None:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            return float(out.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            return None

    # ── Helpers ────────────────────────────────────────────────────────

    def _find_audio(self, seg_id: str) -> Path | None:
        d = self.config.audio_dir
        if not d.exists():
            return None
        seg_name = self.config.resolve_segment_name(seg_id)
        exact = d / f"{seg_name}.mp3"
        if exact.exists():
            return exact
        for mp3 in d.glob(f"{seg_id}-*.mp3"):
            return mp3
        for mp3 in d.glob(f"*{seg_id}*.mp3"):
            return mp3
        return None

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

