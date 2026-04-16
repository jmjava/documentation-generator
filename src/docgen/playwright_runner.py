"""Playwright visual source runner via external capture scripts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class PlaywrightError(RuntimeError):
    """Raised when Playwright capture fails."""


class PlaywrightRunner:
    """Runs user-provided browser capture scripts for docgen segments."""

    def __init__(self, config: Config, timeout_sec: int | None = None) -> None:
        self.config = config
        self.timeout_sec = (
            int(timeout_sec)
            if timeout_sec is not None
            else int(self.config.playwright_timeout_sec)
        )

    def capture_segment(self, seg_id: str, vmap: dict[str, Any]) -> Path:
        """Capture (or resolve) segment video for `type: playwright` visual map."""
        source = str(vmap.get("source", "")).strip()
        if not source:
            raise PlaywrightError(
                f"visual_map[{seg_id}] type=playwright requires a 'source' output path"
            )
        output_path = self._resolve_output_path(source)

        script = str(vmap.get("script", "")).strip()
        if not script:
            if output_path.exists():
                return output_path
            raise PlaywrightError(
                f"type=playwright source missing and no script configured: {output_path}"
            )

        script_path = self._resolve_path(script)
        if not script_path.exists():
            raise PlaywrightError(f"Playwright script not found: {script_path}")

        url = str(vmap.get("url", "")).strip() or None
        viewport = vmap.get("viewport", {}) or {}
        width = int(viewport.get("width", 1920))
        height = int(viewport.get("height", 1080))
        args = [str(a) for a in (vmap.get("args", []) or [])]

        return self.capture(
            script=script_path,
            output=output_path,
            url=url,
            viewport={"width": width, "height": height},
            args=args,
            segment_id=seg_id,
        )

    def capture(
        self,
        *,
        script: Path | str | None,
        output: Path | str | None = None,
        source: str | None = None,
        url: str | None = None,
        viewport: dict[str, int] | None = None,
        args: list[str] | None = None,
        segment_id: str | None = None,
        timeout_sec: int | None = None,
    ) -> Path:
        """Run one external capture script and return the output video path."""
        if script is None and url is None:
            raise PlaywrightError("capture requires --script or --url")
        if script is None:
            raise PlaywrightError("capture requires --script")

        script_path = self._resolve_path(script)
        output_value = output if output is not None else source
        if output_value is None:
            output_value = "playwright-capture.mp4"
        output_path = self._resolve_output_path(output_value)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        python_bin = self.config.playwright_python_path or sys.executable
        env = os.environ.copy()
        env["DOCGEN_PLAYWRIGHT_OUTPUT"] = str(output_path)
        if url:
            env["DOCGEN_PLAYWRIGHT_URL"] = url
        if segment_id:
            env["DOCGEN_PLAYWRIGHT_SEGMENT"] = segment_id
        vp = viewport or {}
        width = int(vp.get("width", 1920))
        height = int(vp.get("height", 1080))
        env["DOCGEN_PLAYWRIGHT_WIDTH"] = str(width)
        env["DOCGEN_PLAYWRIGHT_HEIGHT"] = str(height)
        env["DOCGEN_PLAYWRIGHT_VIEWPORT"] = f"{width}x{height}"

        effective_timeout = max(1, int(timeout_sec if timeout_sec is not None else self.timeout_sec))
        env["DOCGEN_PLAYWRIGHT_TIMEOUT_SEC"] = str(effective_timeout)

        cmd = [python_bin, str(script_path), *(args or [])]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.config.base_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=True,
            )
        except FileNotFoundError:
            raise PlaywrightError(f"python executable not found: {python_bin}")
        except subprocess.TimeoutExpired:
            raise PlaywrightError(
                f"Playwright capture timed out after {effective_timeout}s ({script_path.name})"
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "")[:400]
            raise PlaywrightError(
                f"Playwright script failed ({script_path.name}): {detail}"
            )

        if not output_path.exists():
            detail = (result.stderr or result.stdout or "").strip()
            hint = f" ({detail[:200]})" if detail else ""
            raise PlaywrightError(
                f"Playwright script finished but output is missing: {output_path}{hint}"
            )
        return output_path

    def _resolve_path(self, value: Path | str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.config.base_dir / path).resolve()

    def _resolve_output_path(self, value: Path | str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        # Source values are normally relative to terminal/rendered.
        if path.parent == Path("."):
            return (self.config.terminal_dir / "rendered" / path).resolve()
        return (self.config.base_dir / path).resolve()
