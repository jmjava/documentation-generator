"""Tests for docgen.scene_lint — detect weight=BOLD and positional color args."""

from docgen.scene_lint import lint_scene_file


def test_clean_scene(tmp_path):
    scene = tmp_path / "scenes.py"
    scene.write_text(
        'from manim import *\n'
        'class MyScene(Scene):\n'
        '    def construct(self):\n'
        '        t = Text("Hello", font_size=36, color=WHITE)\n'
    )
    result = lint_scene_file(scene)
    assert result.passed
    assert result.issues == []


def test_detects_weight_bold(tmp_path):
    scene = tmp_path / "scenes.py"
    scene.write_text(
        'from manim import *\n'
        'class MyScene(Scene):\n'
        '    def construct(self):\n'
        '        t = Text("Title", weight=BOLD, font_size=36)\n'
    )
    result = lint_scene_file(scene)
    assert not result.passed
    assert any("weight=BOLD" in i for i in result.issues)


def test_detects_positional_hex_color(tmp_path):
    scene = tmp_path / "scenes.py"
    scene.write_text(
        'from manim import *\n'
        'class MyScene(Scene):\n'
        '    def construct(self):\n'
        '        t = Text("Hello", "#2979ff", font_size=14)\n'
    )
    result = lint_scene_file(scene)
    assert not result.passed
    assert any("positional" in i for i in result.issues)


def test_detects_positional_color_constant(tmp_path):
    scene = tmp_path / "scenes.py"
    scene.write_text(
        'from manim import *\n'
        'class MyScene(Scene):\n'
        '    def construct(self):\n'
        '        t = Text("Hello", C_BLUE, font_size=14)\n'
    )
    result = lint_scene_file(scene)
    assert not result.passed
    assert any("positional" in i for i in result.issues)


def test_ignores_comments(tmp_path):
    scene = tmp_path / "scenes.py"
    scene.write_text(
        '# weight=BOLD is banned\n'
        '# Text("Hello", C_BLUE)\n'
    )
    result = lint_scene_file(scene)
    assert result.passed


def test_missing_file(tmp_path):
    result = lint_scene_file(tmp_path / "missing.py")
    assert result.passed


def test_multiple_issues(tmp_path):
    scene = tmp_path / "scenes.py"
    scene.write_text(
        'from manim import *\n'
        'class MyScene(Scene):\n'
        '    def construct(self):\n'
        '        t = Text("Title", weight=BOLD)\n'
        '        u = Text("Sub", "#ff0000")\n'
    )
    result = lint_scene_file(scene)
    assert not result.passed
    assert len(result.issues) == 2
