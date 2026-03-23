"""VHS terminal recorder wrapper with error scanning."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config

ERROR_PATTERNS = [
    r"command not found",
    r"No such file or directory",
    r"Permission denied",
    r"syntax error",
    r"bash: ",
    r"error:",
]


@dataclass
class VHSResult:
    tape: str
    success: bool
    errors: list[str] = field(default_factory=list)
    output_path: str | None = None


class VHSRunner:
    def __init__(self, config: Config) -> None:
        self.config = config

    def render(self, tape: str | None = None, strict: bool = False) -> list[VHSResult]:
        terminal_dir = self.config.terminal_dir
        if not terminal_dir.exists():
            print("[vhs] No terminal directory found")
            return []

        if tape:
            tapes = [terminal_dir / tape] if (terminal_dir / tape).exists() else list(
                terminal_dir.glob(f"*{tape}*")
            )
        else:
            tapes = sorted(terminal_dir.glob("*.tape"))

        results: list[VHSResult] = []
        for t in tapes:
            results.append(self._render_one(t, strict))
        return results

    def _render_one(self, tape_path: Path, strict: bool) -> VHSResult:
        print(f"[vhs] Rendering {tape_path.name}")
        try:
            proc = subprocess.run(
                ["vhs", str(tape_path)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(tape_path.parent),
            )
        except FileNotFoundError:
            return VHSResult(tape=tape_path.name, success=False, errors=["vhs not found in PATH"])
        except subprocess.TimeoutExpired:
            return VHSResult(tape=tape_path.name, success=False, errors=["VHS render timed out"])

        combined = proc.stdout + "\n" + proc.stderr
        errors = self._scan_output(combined)

        if strict and errors:
            print(f"[vhs] STRICT FAIL {tape_path.name}: {errors}")
            return VHSResult(tape=tape_path.name, success=False, errors=errors)

        success = proc.returncode == 0 and not errors
        if not success and proc.returncode != 0:
            errors.append(f"Exit code {proc.returncode}")

        return VHSResult(
            tape=tape_path.name,
            success=success,
            errors=errors,
            output_path=str(self.config.terminal_dir / "rendered"),
        )

    @staticmethod
    def _scan_output(text: str) -> list[str]:
        found: list[str] = []
        for line in text.splitlines():
            for pat in ERROR_PATTERNS:
                if re.search(pat, line, re.IGNORECASE):
                    found.append(line.strip()[:120])
                    break
        return found
