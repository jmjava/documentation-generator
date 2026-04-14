"""Static lint checks for Manim scene source files."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class ManimSceneLintIssue:
    kind: str
    line: int
    message: str


@dataclass
class ManimSceneLintResult:
    passed: bool
    issues: list[ManimSceneLintIssue] = field(default_factory=list)
    default_fonts: list[str] = field(default_factory=list)
    explicit_fonts: list[str] = field(default_factory=list)


class ManimSceneLinter:
    def __init__(self, config: Config) -> None:
        self.expected_font = config.manim_font
        self.lint_cfg = config.manim_lint_config

    def lint_file(self, path: str | Path) -> ManimSceneLintResult:
        return lint_scene_file(
            path,
            expected_font=self.expected_font,
            deny_weight_bold=bool(self.lint_cfg.get("deny_weight_bold", True)),
            deny_positional_text_color=bool(self.lint_cfg.get("deny_positional_text_color", True)),
            enforce_single_font=bool(self.lint_cfg.get("enforce_single_font", True)),
        )


def lint_scene_file(
    path: str | Path,
    expected_font: str,
    *,
    deny_weight_bold: bool = True,
    deny_positional_text_color: bool = True,
    enforce_single_font: bool = True,
) -> ManimSceneLintResult:
    path = Path(path)
    if not path.exists():
        return ManimSceneLintResult(
            passed=True,
            issues=[ManimSceneLintIssue("missing", 0, f"scene file missing: {path}")],
        )

    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return ManimSceneLintResult(
            passed=False,
            issues=[ManimSceneLintIssue("syntax", exc.lineno or 0, f"syntax error: {exc.msg}")],
        )

    default_fonts: list[tuple[int, str]] = []
    text_fonts: list[tuple[int, str]] = []
    issues: list[ManimSceneLintIssue] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Text.set_default(font="...")
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "set_default"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "Text"
        ):
            for kw in node.keywords:
                if kw.arg == "font" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    default_fonts.append((getattr(node, "lineno", 0), kw.value.value.strip()))

        # Text(..., font="...")
        if isinstance(node.func, ast.Name) and node.func.id == "Text":
            if deny_weight_bold:
                for kw in node.keywords:
                    if kw.arg == "weight" and isinstance(kw.value, ast.Name) and kw.value.id == "BOLD":
                        issues.append(
                            ManimSceneLintIssue(
                                "font_weight",
                                getattr(node, "lineno", 0),
                                "Text(..., weight=BOLD) may trigger font substitution; use size/color emphasis",
                            )
                        )
            for kw in node.keywords:
                if kw.arg == "font" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    text_fonts.append((getattr(node, "lineno", 0), kw.value.value.strip()))
            if deny_positional_text_color and len(node.args) >= 2:
                second = node.args[1]
                if _looks_like_color_arg(second):
                    issues.append(
                        ManimSceneLintIssue(
                            "text_positional_color",
                            getattr(node, "lineno", 0),
                            "Text color must be keyword arg (`color=...`), not positional arg 2",
                        )
                    )

    unique_defaults = sorted({font for _, font in default_fonts})
    unique_text_fonts = sorted({font for _, font in text_fonts})
    unique_all = sorted(set(unique_defaults) | set(unique_text_fonts))

    if enforce_single_font and not default_fonts:
        issues.append(
            ManimSceneLintIssue(
                "missing_default_font",
                0,
                "Text.set_default(font=...) not found; set one global font family",
            )
        )
    elif enforce_single_font and len(unique_defaults) > 1:
        issues.append(
            ManimSceneLintIssue(
                "multiple_defaults",
                default_fonts[0][0],
                f"Multiple Text.set_default fonts found: {', '.join(unique_defaults)}",
            )
        )

    if enforce_single_font and len(unique_all) > 1:
        issues.append(
            ManimSceneLintIssue(
                "mixed_font",
                0,
                f"Multiple font families detected in scene file: {', '.join(unique_all)}",
            )
        )

    if enforce_single_font and unique_all and expected_font not in unique_all:
        issues.append(
            ManimSceneLintIssue(
                "expected_font_missing",
                0,
                f"Expected font '{expected_font}' not found; detected: {', '.join(unique_all)}",
            )
        )
    if enforce_single_font and expected_font in unique_all and len(unique_all) > 1:
        issues.append(
            ManimSceneLintIssue(
                "mixed_font",
                0,
                f"Expected single font '{expected_font}', but other families are present",
            )
        )

    return ManimSceneLintResult(
        passed=len(issues) == 0,
        issues=issues,
        default_fonts=[font for _, font in default_fonts],
        explicit_fonts=[font for _, font in text_fonts],
    )


def _looks_like_color_arg(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(re.match(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$", node.value.strip()))
    if isinstance(node, ast.Name):
        return bool(re.match(r"^(C_[A-Z0-9_]+|WHITE|BLACK|GRAY|GREY.*|RED|GREEN|BLUE|YELLOW|ORANGE|PURPLE)$", node.id))
    return False
