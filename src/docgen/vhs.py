"""VHS terminal recorder wrapper with error scanning and tape linting."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from docgen.binaries import resolve_binary

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

_CLEAN_BASHRC = """\
# Minimal bashrc for VHS recordings — no prompt stacking, no git helpers.
export PS1='$ '
"""

RISKY_TAPE_COMMANDS = (
    re.compile(r"^\s*Type\s+\".*\bpython(?:3)?\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bcurl\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bwget\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bnpm\s+(start|run)\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\byarn\s+(start|dev)\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bnode\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bdocker\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bdocker-compose\b.*\"", re.IGNORECASE),
    re.compile(r"^\s*Type\s+\".*\bkubectl\b.*\"", re.IGNORECASE),
)


@dataclass
class TapeLintIssue:
    tape: str
    line: int
    text: str
    message: str

    def __str__(self) -> str:
        return f"L{self.line}: {self.message} :: {self.text}"


@dataclass
class TapeLintResult:
    tape: str
    issues: list[TapeLintIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


@dataclass
class VHSResult:
    tape: str
    success: bool
    errors: list[str] = field(default_factory=list)
    output_path: str | None = None


class VHSRunner:
    def __init__(self, config: Config, render_timeout_sec: int | None = None) -> None:
        self.config = config
        self.render_timeout_sec = render_timeout_sec

    def render(
        self,
        tape: str | None = None,
        strict: bool = False,
        timeout_sec: int | None = None,
    ) -> list[VHSResult]:
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
        effective_timeout = timeout_sec
        if effective_timeout is None:
            effective_timeout = (
                self.render_timeout_sec
                if self.render_timeout_sec is not None
                else self.config.vhs_render_timeout_sec
            )
        for t in tapes:
            results.append(self._render_one(t, strict, effective_timeout))
        return results

    def lint_tapes(self, tape: str | None = None) -> list[TapeLintResult]:
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

        return [self._lint_one(path) for path in tapes]

    @staticmethod
    def _clean_env() -> dict[str, str]:
        """Build a minimal environment that produces a clean VHS recording.

        Problems this solves:
        - (.venv) stacking: .bashrc re-activates the venv on every prompt
        - parse_git_branch: command not found: PS1 references missing functions
        - PROMPT_COMMAND noise: running extra commands on every prompt
        - PATH pollution: duplicated venv bin entries

        Strategy: build PATH from scratch with only the venv bin + system dirs.
        Redirect HOME to a temp dir with a minimal .bashrc.
        Tapes MUST use ``Set Shell "bash --norc --noprofile"`` to skip
        all user/system startup files unconditionally.
        """
        fake_home = tempfile.mkdtemp(prefix="vhs_home_")
        Path(fake_home, ".bashrc").write_text(_CLEAN_BASHRC)

        venv_bin = os.environ.get("VIRTUAL_ENV", "")
        if venv_bin:
            venv_bin = str(Path(venv_bin) / "bin")

        seen: set[str] = set()
        clean_path_parts: list[str] = []
        for p in os.environ.get("PATH", "").split(os.pathsep):
            if p in seen:
                continue
            seen.add(p)
            if ".venv" in p and p != venv_bin:
                continue
            clean_path_parts.append(p)
        if venv_bin and venv_bin not in seen:
            clean_path_parts.insert(0, venv_bin)

        env = {
            "PATH": os.pathsep.join(clean_path_parts),
            "HOME": fake_home,
            "PS1": "$ ",
            "TERM": os.environ.get("TERM", "xterm-256color"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "USER": os.environ.get("USER", "user"),
        }
        return env

    def _render_one(self, tape_path: Path, strict: bool, timeout_sec: int) -> VHSResult:
        print(f"[vhs] Rendering {tape_path.name}")
        env = self._clean_env()
        vhs_bin = self._resolve_vhs_binary()
        if not vhs_bin:
            return VHSResult(
                tape=tape_path.name,
                success=False,
                errors=[
                    "vhs not found. Install VHS or set vhs.vhs_path in docgen.yaml.",
                ],
            )
        start = time.monotonic()
        try:
            proc = subprocess.run(
                [vhs_bin, str(tape_path)],
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_sec)),
                cwd=str(tape_path.parent),
                env=env,
            )
        except FileNotFoundError:
            return VHSResult(tape=tape_path.name, success=False, errors=["vhs not found in PATH"])
        except subprocess.TimeoutExpired:
            return VHSResult(
                tape=tape_path.name,
                success=False,
                errors=[
                    f"VHS render timed out after {timeout_sec}s.",
                    "Tip: use `docgen tape-lint` and prefer `Type \"echo ...\"` simulated output.",
                ],
            )
        finally:
            fake_home = env.get("HOME", "")
            if fake_home and "vhs_home_" in fake_home:
                import shutil
                shutil.rmtree(fake_home, ignore_errors=True)

        combined = proc.stdout + "\n" + proc.stderr
        errors = self._scan_output(combined)

        if strict and errors:
            print(f"[vhs] STRICT FAIL {tape_path.name}: {errors}")
            return VHSResult(tape=tape_path.name, success=False, errors=errors)

        success = proc.returncode == 0 and not errors
        if not success and proc.returncode != 0:
            errors.append(f"Exit code {proc.returncode}")
        elapsed = time.monotonic() - start
        print(f"[vhs] Finished {tape_path.name} in {elapsed:.1f}s")

        return VHSResult(
            tape=tape_path.name,
            success=success,
            errors=errors,
            output_path=str(self.config.terminal_dir / "rendered"),
        )

    def _lint_one(self, tape_path: Path) -> TapeLintResult:
        result = TapeLintResult(tape=tape_path.name)
        result.issues.extend(self.scan_tape_for_risky_commands(tape_path))
        return result

    @staticmethod
    def scan_tape_for_risky_commands(tape_path: Path) -> list[TapeLintIssue]:
        """Return lint issues for risky Type commands in a tape file."""
        try:
            lines = tape_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return [
                TapeLintIssue(
                    tape=tape_path.name,
                    line=0,
                    text="",
                    message=f"Could not read tape: {exc}",
                )
            ]

        issues: list[TapeLintIssue] = []
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered.startswith('type "echo ') or lowered.startswith("type 'echo "):
                continue
            for pattern in RISKY_TAPE_COMMANDS:
                if pattern.search(stripped):
                    issues.append(
                        TapeLintIssue(
                            tape=tape_path.name,
                            line=idx,
                            text=stripped[:160],
                            message=(
                                "Potentially real/external command in tape. "
                                "Prefer simulated output with `Type \"echo ...\"`."
                            ),
                        )
                    )
                    break
        return issues

    @staticmethod
    def _scan_output(text: str) -> list[str]:
        found: list[str] = []
        for line in text.splitlines():
            for pat in ERROR_PATTERNS:
                if re.search(pat, line, re.IGNORECASE):
                    found.append(line.strip()[:120])
                    break
        return found

    def _resolve_vhs_binary(self) -> str | None:
        configured = self.config.vhs_path
        if configured and not Path(configured).is_absolute():
            configured = str((self.config.base_dir / configured).resolve())

        candidates = [
            Path.home() / "go" / "bin" / "vhs",
            "/usr/local/bin/vhs",
            "/snap/bin/vhs",
        ]
        resolution = resolve_binary("vhs", configured_path=configured, extra_candidates=candidates)
        if resolution.path:
            return resolution.path

        print("[vhs] VHS executable not found.")
        if resolution.tried:
            print("[vhs] Tried:")
            for candidate in resolution.tried:
                print(f"  - {candidate}")
        print(
            "[vhs] Fix: install VHS and ensure it is executable, or set "
            "`vhs.vhs_path` in docgen.yaml."
        )
        return None
