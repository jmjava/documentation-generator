"""VHS terminal recorder wrapper with error scanning."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
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

    def _render_one(self, tape_path: Path, strict: bool) -> VHSResult:
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
        try:
            proc = subprocess.run(
                [vhs_bin, str(tape_path)],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(tape_path.parent),
                env=env,
            )
        except FileNotFoundError:
            return VHSResult(tape=tape_path.name, success=False, errors=["vhs not found in PATH"])
        except subprocess.TimeoutExpired:
            return VHSResult(tape=tape_path.name, success=False, errors=["VHS render timed out"])
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
