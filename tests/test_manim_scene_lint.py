"""Tests for Manim scene source linting checks."""

from __future__ import annotations

from pathlib import Path

from docgen.config import Config
from docgen.manim_scene_lint import ManimSceneLinter


def _config_for(tmp_path: Path) -> Config:
    cfg_path = tmp_path / "docgen.yaml"
    cfg_path.write_text("manim:\n  font: Liberation Sans\n", encoding="utf-8")
    return Config.from_yaml(cfg_path)


def test_font_lint_passes_single_family(tmp_path: Path) -> None:
    cfg = _config_for(tmp_path)
    scene_path = tmp_path / "scene.py"
    scene_path.write_text(
        "\n".join(
            [
                "from manim import *",
                'Text.set_default(font="Liberation Sans")',
                "class Demo(Scene):",
                "    def construct(self):",
                '        Text("ok", font_size=24, color=WHITE)',
            ]
        ),
        encoding="utf-8",
    )

    report = ManimSceneLinter(cfg).lint_file(scene_path)
    assert report.passed


def test_font_lint_flags_weight_bold(tmp_path: Path) -> None:
    cfg = _config_for(tmp_path)
    scene_path = tmp_path / "scene.py"
    scene_path.write_text(
        "\n".join(
            [
                "from manim import *",
                'Text.set_default(font="Liberation Sans")',
                "class Demo(Scene):",
                "    def construct(self):",
                '        Text("bad", font_size=24, color=WHITE, weight=BOLD)',
            ]
        ),
        encoding="utf-8",
    )

    report = ManimSceneLinter(cfg).lint_file(scene_path)
    assert not report.passed
    assert any(issue.kind == "font_weight" for issue in report.issues)


def test_font_lint_flags_mixed_font_overrides(tmp_path: Path) -> None:
    cfg = _config_for(tmp_path)
    scene_path = tmp_path / "scene.py"
    scene_path.write_text(
        "\n".join(
            [
                "from manim import *",
                'Text.set_default(font="Liberation Sans")',
                "class Demo(Scene):",
                "    def construct(self):",
                '        Text("a", font_size=24, color=WHITE, font="Liberation Sans")',
                '        Text("b", font_size=24, color=WHITE, font="DejaVu Sans")',
            ]
        ),
        encoding="utf-8",
    )

    report = ManimSceneLinter(cfg).lint_file(scene_path)
    assert not report.passed
    assert any(issue.kind == "mixed_font" for issue in report.issues)


def test_font_lint_flags_positional_text_color(tmp_path: Path) -> None:
    cfg = _config_for(tmp_path)
    scene_path = tmp_path / "scene.py"
    scene_path.write_text(
        "\n".join(
            [
                "from manim import *",
                'Text.set_default(font="Liberation Sans")',
                "class Demo(Scene):",
                "    def construct(self):",
                '        Text("bad", C_BLUE, font_size=14)',
            ]
        ),
        encoding="utf-8",
    )

    report = ManimSceneLinter(cfg).lint_file(scene_path)
    assert not report.passed
    assert any(issue.kind == "text_positional_color" for issue in report.issues)
