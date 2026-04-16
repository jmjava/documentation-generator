"""Run existing Playwright test suites with video + tracing enabled.

Unlike :mod:`docgen.playwright_runner` (which runs custom capture scripts),
this module invokes the project's *existing* Playwright tests and harvests
the video and trace artifacts they produce.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class PlaywrightTestError(RuntimeError):
    """Raised when test execution fails fatally."""


@dataclass
class RunResult:
    """Result of running a single test or test suite."""

    test: str
    success: bool = True
    video_path: Path | None = None
    trace_path: Path | None = None
    errors: list[str] = field(default_factory=list)
    duration_sec: float = 0.0


class PlaywrightTestRunner:
    """Invoke Playwright tests and collect video + trace artifacts."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._pt_cfg = config.playwright_test_config

    def run_tests(
        self,
        *,
        test_filter: str | None = None,
        timeout_sec: int | None = None,
    ) -> list[RunResult]:
        """Run tests and return results with artifact paths."""
        framework = self._pt_cfg.get("framework", "pytest")
        effective_timeout = timeout_sec or int(self._pt_cfg.get("timeout_sec", 300))

        if framework == "pytest":
            return self._run_pytest(test_filter, effective_timeout)
        elif framework == "playwright":
            return self._run_npx_playwright(test_filter, effective_timeout)
        else:
            raise PlaywrightTestError(f"Unknown test framework: {framework}")

    def run_segment_tests(self) -> list[RunResult]:
        """Run tests only for segments with type: playwright_test in visual_map."""
        results: list[RunResult] = []
        for seg_id, vmap in self.config.visual_map.items():
            if vmap.get("type") != "playwright_test":
                continue
            test_ref = vmap.get("test", "")
            if not test_ref:
                print(f"[playwright-test] SKIP {seg_id}: no 'test' specified in visual_map")
                continue
            print(f"[playwright-test] Running {seg_id}: {test_ref}")
            segment_results = self.run_tests(test_filter=test_ref)
            for r in segment_results:
                self._collect_artifacts(seg_id, vmap, r)
            results.extend(segment_results)
        return results

    # ------------------------------------------------------------------
    # Framework-specific runners
    # ------------------------------------------------------------------

    def _run_pytest(self, test_filter: str | None, timeout_sec: int) -> list[RunResult]:
        test_dir = self._resolve_test_dir()
        video_dir = self._resolve_video_dir()
        trace_dir = self._resolve_trace_dir()
        video_dir.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)

        custom_cmd = self._pt_cfg.get("test_command", "").strip()
        if custom_cmd:
            cmd = custom_cmd.split()
        else:
            cmd = [
                "python3", "-m", "pytest",
                str(test_dir),
                f"--video={'on'}",
                f"--tracing={'on'}",
                f"--output={video_dir}",
                "-x",
            ]
            if test_filter:
                cmd.extend(["-k", test_filter])

        env = os.environ.copy()
        env["PLAYWRIGHT_VIDEO_DIR"] = str(video_dir)
        env["PLAYWRIGHT_TRACE_DIR"] = str(trace_dir)

        result = RunResult(test=test_filter or str(test_dir))
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.config.repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            result.success = proc.returncode == 0
            if not result.success and self._pt_cfg.get("retain_on_failure", True):
                result.errors.append(f"Tests exited with code {proc.returncode}")
                stderr_tail = (proc.stderr or "")[-500:]
                if stderr_tail:
                    result.errors.append(stderr_tail)
            elif not result.success:
                raise PlaywrightTestError(
                    f"Tests failed (exit {proc.returncode}): "
                    f"{(proc.stderr or proc.stdout or '')[:400]}"
                )
        except subprocess.TimeoutExpired:
            result.success = False
            result.errors.append(f"Tests timed out after {timeout_sec}s")
        except FileNotFoundError as exc:
            result.success = False
            result.errors.append(f"Command not found: {exc}")

        self._find_artifacts(result, video_dir, trace_dir)
        return [result]

    def _run_npx_playwright(self, test_filter: str | None, timeout_sec: int) -> list[RunResult]:
        test_dir = self._resolve_test_dir()
        video_dir = self._resolve_video_dir()
        trace_dir = self._resolve_trace_dir()

        custom_cmd = self._pt_cfg.get("test_command", "").strip()
        if custom_cmd:
            cmd = custom_cmd.split()
        else:
            cmd = ["npx", "playwright", "test"]
            if test_filter:
                cmd.append(test_filter)
            cmd.extend(["--trace", "on"])

        env = os.environ.copy()
        env["PLAYWRIGHT_VIDEO_DIR"] = str(video_dir)

        result = RunResult(test=test_filter or str(test_dir))
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.config.repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            result.success = proc.returncode == 0
            if not result.success:
                result.errors.append(f"Tests exited with code {proc.returncode}")
        except subprocess.TimeoutExpired:
            result.success = False
            result.errors.append(f"Tests timed out after {timeout_sec}s")
        except FileNotFoundError as exc:
            result.success = False
            result.errors.append(f"Command not found: {exc}")

        self._find_artifacts(result, video_dir, trace_dir)
        return [result]

    # ------------------------------------------------------------------
    # Artifact collection
    # ------------------------------------------------------------------

    def _find_artifacts(
        self,
        result: RunResult,
        video_dir: Path,
        trace_dir: Path,
    ) -> None:
        """Scan output directories for the latest video and trace files."""
        if video_dir.exists():
            videos = sorted(video_dir.glob("**/*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not videos:
                videos = sorted(video_dir.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
            if videos:
                result.video_path = videos[0]

        if trace_dir.exists():
            traces = sorted(trace_dir.glob("**/*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
            if traces:
                result.trace_path = traces[0]

    def _collect_artifacts(
        self, seg_id: str, vmap: dict[str, Any], result: RunResult
    ) -> None:
        """Copy artifacts to the expected locations for compose."""
        source_path = vmap.get("source", "")
        if source_path and result.video_path and result.video_path.exists():
            dest = self.config.base_dir / source_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(result.video_path, dest)
            print(f"[playwright-test] Copied video to {dest}")

        trace_path = vmap.get("trace", "")
        if trace_path and result.trace_path and result.trace_path.exists():
            dest = self.config.base_dir / trace_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(result.trace_path, dest)
            print(f"[playwright-test] Copied trace to {dest}")

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_test_dir(self) -> Path:
        rel = self._pt_cfg.get("test_dir", "tests/e2e")
        return (self.config.repo_root / rel).resolve()

    def _resolve_video_dir(self) -> Path:
        rel = self._pt_cfg.get("video_dir", "test-results/videos")
        return (self.config.base_dir / rel).resolve()

    def _resolve_trace_dir(self) -> Path:
        rel = self._pt_cfg.get("trace_dir", "test-results/traces")
        return (self.config.base_dir / rel).resolve()
