"""Lint Manim scene files for known pitfalls: bold weight, positional color args."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class SceneLintResult:
    path: str
    passed: bool
    issues: list[str] = field(default_factory=list)


_BOLD_PATTERN = re.compile(r"\bweight\s*=\s*BOLD\b")

_TEXT_POSITIONAL_COLOR = re.compile(
    r"""Text\(\s*(?:f?["'][^"']*["']|[A-Za-z_]\w*)\s*,\s*["']#[0-9a-fA-F]""",
)

_TEXT_POSITIONAL_COLOR_VAR = re.compile(
    r"""Text\(\s*(?:f?["'][^"']*["']|[A-Za-z_]\w*)\s*,\s*C_[A-Z_]+""",
)


def lint_scene_file(path: Path) -> SceneLintResult:
    """Scan a single Manim scene file for known issues."""
    result = SceneLintResult(path=str(path), passed=True)

    if not path.exists():
        return result

    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        if _BOLD_PATTERN.search(line):
            result.issues.append(
                f"Line {lineno}: weight=BOLD causes Pango font substitution — "
                f"use font_size and color for emphasis instead"
            )
            result.passed = False

        if _TEXT_POSITIONAL_COLOR.search(line) or _TEXT_POSITIONAL_COLOR_VAR.search(line):
            result.issues.append(
                f"Line {lineno}: color passed as positional arg to Text() — "
                f"use keyword: Text(..., color=C_COLOR)"
            )
            result.passed = False

    return result


def lint_scene_dir(config: Config) -> list[SceneLintResult]:
    """Lint all .py files under the animations directory."""
    anim_dir = config.animations_dir
    if not anim_dir.exists():
        return []

    results: list[SceneLintResult] = []
    for py_file in sorted(anim_dir.glob("**/*.py")):
        if py_file.name.startswith("_"):
            continue
        result = lint_scene_file(py_file)
        if result.issues:
            results.append(result)
    return results
