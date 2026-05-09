"""Unit tests for ``docgen.scene_generate``.

Covers settings merge, class-name derivation, response parsing/validation,
marker-block injection (idempotent regeneration), and the bootstrap path for
fresh ``scenes.py`` files. The OpenAI call is mocked end-to-end; no network or
``OPENAI_API_KEY`` is required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from docgen.config import Config
from docgen.scene_generate import (
    BOOTSTRAP_HEADER,
    DEFAULT_MODEL,
    REQUIRED_HELPERS,
    SceneGenerationError,
    derive_class_name,
    ensure_scenes_bootstrap,
    extract_reference_classes,
    generate_scene,
    inject_or_replace,
    lint_generated_block,
    merged_scene_generation_settings,
    strip_response_fences,
    validate_class_definition,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


def _write_cfg(tmp_path: Path, overrides: dict | None = None) -> Config:
    cfg: dict = {
        "dirs": {
            "narration": "narration",
            "animations": "animations",
            "audio": "audio",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {"default": ["08"], "all": ["08"]},
        "segment_names": {"08": "08-demo-function"},
        "visual_map": {"08": {"type": "manim", "scene": "DemoFunctionScene", "source": "DemoFunctionScene.mp4"}},
    }
    if overrides:
        cfg.update(overrides)
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


# ── Settings merge ─────────────────────────────────────────────────────────


def test_settings_default_when_yaml_block_missing(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path)
    s = merged_scene_generation_settings(cfg, "08")
    assert s.model == DEFAULT_MODEL
    assert s.hints == []
    assert s.context_paths == []
    assert s.class_name is None


def test_settings_root_and_segment_overrides_merge(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path,
        {
            "manim_scene_generation": {
                "model": "gpt-4o-mini",
                "temperature": 0.2,
                "hints": ["root-hint"],
                "context": {"paths": ["src/docgen/cli.py"], "globs": []},
                "segments": {
                    "08": {
                        "class_name": "DemoFunctionScene",
                        "hints": ["seg-hint-1", "seg-hint-2"],
                        "context": {"paths": ["src/docgen/demo_function.py"]},
                    }
                },
            }
        },
    )
    s = merged_scene_generation_settings(cfg, "08")
    assert s.model == "gpt-4o-mini"
    assert s.temperature == pytest.approx(0.2)
    assert s.hints == ["root-hint", "seg-hint-1", "seg-hint-2"]
    assert s.context_paths == ["src/docgen/cli.py", "src/docgen/demo_function.py"]
    assert s.class_name == "DemoFunctionScene"


# ── Class-name derivation ──────────────────────────────────────────────────


def test_derive_class_name_uses_override_when_provided() -> None:
    assert derive_class_name("08", "08-demo-function", "MyScene") == "MyScene"


def test_derive_class_name_strips_leading_id_and_camelizes() -> None:
    assert derive_class_name("08", "08-demo-function", None) == "DemoFunctionScene"


def test_derive_class_name_handles_underscore_and_spaces() -> None:
    assert derive_class_name("12", "12_my segment", None) == "MySegmentScene"


def test_derive_class_name_falls_back_to_segment_id_when_name_empty() -> None:
    assert derive_class_name("08", "", None) == "Segment08Scene"


# ── Validation ─────────────────────────────────────────────────────────────


_GOOD_CLASS = (
    "class DemoFunctionScene(_TimedScene):\n"
    "    def construct(self):\n"
    "        self.camera.background_color = C_BG\n"
    "        title = Text('demo', font_size=42, color=C_ACCENT)\n"
    "        self.timed_play(Write(title), run_time=1.0)\n"
    "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
    "        self.timed_wait(0.5)\n"
)


def test_validate_accepts_timed_scene_subclass() -> None:
    cls = validate_class_definition(_GOOD_CLASS, "DemoFunctionScene")
    assert cls.name == "DemoFunctionScene"


def test_validate_rejects_empty_output() -> None:
    with pytest.raises(SceneGenerationError, match="empty"):
        validate_class_definition("", "Anything")


def test_validate_rejects_syntax_error() -> None:
    with pytest.raises(SceneGenerationError, match="parse"):
        validate_class_definition("class Foo(_TimedScene)\n  pass", "Foo")


def test_validate_rejects_no_class() -> None:
    with pytest.raises(SceneGenerationError, match="no class"):
        validate_class_definition("x = 1\n", "Foo")


def test_validate_rejects_multiple_classes() -> None:
    code = (
        "class A(_TimedScene):\n    pass\n"
        "class B(_TimedScene):\n    pass\n"
    )
    with pytest.raises(SceneGenerationError, match="multiple"):
        validate_class_definition(code, "A")


def test_validate_rejects_module_level_statements() -> None:
    code = "import os\nclass A(_TimedScene):\n    pass\n"
    with pytest.raises(SceneGenerationError, match="non-class"):
        validate_class_definition(code, "A")


def test_validate_rejects_class_name_mismatch() -> None:
    with pytest.raises(SceneGenerationError, match="mismatch"):
        validate_class_definition(_GOOD_CLASS, "OtherScene")


def test_validate_rejects_wrong_base_class() -> None:
    code = "class Foo(int):\n    pass\n"
    with pytest.raises(SceneGenerationError, match="must extend"):
        validate_class_definition(code, "Foo")


# ── Fence stripping ────────────────────────────────────────────────────────


def test_strip_fences_removes_python_fence() -> None:
    fenced = "```python\nclass A(_TimedScene):\n    pass\n```"
    assert strip_response_fences(fenced) == "class A(_TimedScene):\n    pass"


def test_strip_fences_removes_bare_fence() -> None:
    fenced = "```\nclass A(_TimedScene):\n    pass\n```"
    assert strip_response_fences(fenced) == "class A(_TimedScene):\n    pass"


def test_strip_fences_passthrough_when_no_fence() -> None:
    assert strip_response_fences("class A(_TimedScene): pass") == "class A(_TimedScene): pass"


# ── Marker injection (idempotent regeneration) ─────────────────────────────


def test_inject_appends_when_marker_absent() -> None:
    base = BOOTSTRAP_HEADER
    result = inject_or_replace(base, "08", "DemoFunctionScene", _GOOD_CLASS)
    assert "BEGIN GENERATED SCENE: 08 (DemoFunctionScene)" in result
    assert "END GENERATED SCENE: 08" in result
    assert _GOOD_CLASS.strip() in result
    # Bootstrap is preserved verbatim:
    assert result.startswith(BOOTSTRAP_HEADER)


def test_inject_replaces_existing_block_idempotently() -> None:
    base = BOOTSTRAP_HEADER
    once = inject_or_replace(base, "08", "DemoFunctionScene", _GOOD_CLASS)
    new_class = _GOOD_CLASS.replace("'demo'", "'demo v2'")
    twice = inject_or_replace(once, "08", "DemoFunctionScene", new_class)

    # Only ONE generated block remains:
    assert twice.count("BEGIN GENERATED SCENE: 08 (DemoFunctionScene)") == 1
    assert twice.count("END GENERATED SCENE: 08") == 1
    assert "'demo v2'" in twice
    assert "'demo'" not in twice.replace("'demo v2'", "")
    # And it's still a parsable Python file:
    import ast
    ast.parse(twice)


def test_inject_replaces_block_when_class_name_changes_keeping_seg_id() -> None:
    base = BOOTSTRAP_HEADER
    once = inject_or_replace(base, "08", "OldName", _GOOD_CLASS.replace("DemoFunctionScene", "OldName"))
    twice = inject_or_replace(once, "08", "NewName", _GOOD_CLASS.replace("DemoFunctionScene", "NewName"))
    assert "OldName" not in twice
    assert "BEGIN GENERATED SCENE: 08 (NewName)" in twice
    assert twice.count("END GENERATED SCENE: 08") == 1


# ── Bootstrap ──────────────────────────────────────────────────────────────


def test_ensure_bootstrap_writes_template_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    ensure_scenes_bootstrap(p)
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    for helper in REQUIRED_HELPERS:
        assert helper in text


def test_ensure_bootstrap_leaves_existing_helpers_alone(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    p.write_text(BOOTSTRAP_HEADER, encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    ensure_scenes_bootstrap(p)
    assert p.read_text(encoding="utf-8") == before


def test_ensure_bootstrap_refuses_partial_helpers(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    p.write_text("def _box():\n    return None\n", encoding="utf-8")
    with pytest.raises(SceneGenerationError, match="missing required helpers"):
        ensure_scenes_bootstrap(p)


def test_ensure_bootstrap_refuses_unparsable_file(tmp_path: Path) -> None:
    p = tmp_path / "scenes.py"
    p.write_text("def broken(", encoding="utf-8")
    with pytest.raises(SceneGenerationError, match="did not parse"):
        ensure_scenes_bootstrap(p)


# ── Reference scenes extraction ────────────────────────────────────────────


def test_extract_reference_classes_returns_only_public_classes() -> None:
    text = (
        BOOTSTRAP_HEADER
        + "\nclass DocgenOverviewScene(_TimedScene):\n    def construct(self):\n        pass\n"
        + "\nclass _Helper(_TimedScene):\n    pass\n"
    )
    out = extract_reference_classes(text)
    assert "DocgenOverviewScene" in out
    assert "_Helper" not in out
    # Bootstrap helpers are not echoed back:
    assert "C_BG = " not in out
    assert "def _box" not in out


def test_extract_reference_classes_returns_empty_for_unparsable() -> None:
    assert extract_reference_classes("def broken(") == ""


def test_extract_reference_classes_handles_empty_text() -> None:
    assert extract_reference_classes("") == ""


# ── End-to-end driver (mocked OpenAI) ──────────────────────────────────────


def _setup_project(tmp_path: Path) -> Config:
    """Materialize a minimal docgen project with narration + animations dirs."""
    cfg = _write_cfg(
        tmp_path,
        {
            "manim_scene_generation": {
                "model": "gpt-4o",
                "segments": {"08": {"class_name": "DemoFunctionScene"}},
            }
        },
    )
    (tmp_path / "narration").mkdir()
    (tmp_path / "narration" / "08-demo-function.md").write_text(
        "Spoken narration for segment 08.\n", encoding="utf-8"
    )
    (tmp_path / "animations").mkdir()
    return cfg


def test_generate_scene_dry_run_does_not_call_openai_or_write(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    with patch("docgen.scene_generate.call_llm") as mocked:
        result = generate_scene(
            cfg, "08", extra_paths=[], extra_hints=["audience: engineers"], dry_run=True
        )
    mocked.assert_not_called()
    assert result.written is False
    assert result.cleaned_code == ""
    assert "DemoFunctionScene" in result.prompt
    assert "audience: engineers" in result.prompt
    assert "Spoken narration for segment 08." in result.prompt
    assert not (tmp_path / "animations" / "scenes.py").exists()


def test_generate_scene_writes_to_scenes_py(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    with patch("docgen.scene_generate.call_llm", return_value=_GOOD_CLASS):
        result = generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    assert result.written is True
    assert result.class_name == "DemoFunctionScene"
    out = (tmp_path / "animations" / "scenes.py").read_text(encoding="utf-8")
    assert "class DemoFunctionScene(_TimedScene)" in out
    assert "BEGIN GENERATED SCENE: 08 (DemoFunctionScene)" in out
    # Bootstrap was written first because scenes.py didn't exist:
    for helper in REQUIRED_HELPERS:
        assert helper in out


def test_generate_scene_print_only_validates_but_does_not_write(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    with patch("docgen.scene_generate.call_llm", return_value=_GOOD_CLASS):
        result = generate_scene(cfg, "08", extra_paths=[], extra_hints=[], print_only=True)
    assert result.written is False
    assert "DemoFunctionScene" in result.cleaned_code
    assert not (tmp_path / "animations" / "scenes.py").exists()


def test_generate_scene_strips_fenced_response(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    fenced = f"```python\n{_GOOD_CLASS}```"
    with patch("docgen.scene_generate.call_llm", return_value=fenced):
        result = generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    assert result.written is True
    assert result.cleaned_code.startswith("class DemoFunctionScene")


def test_generate_scene_saves_draft_on_validation_failure(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    bad = "not a class definition at all"
    with patch("docgen.scene_generate.call_llm", return_value=bad):
        with pytest.raises(SceneGenerationError):
            generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    draft = tmp_path / "animations" / ".scene-generate-drafts" / "08.draft.py"
    assert draft.exists()
    assert draft.read_text(encoding="utf-8") == bad
    # scenes.py was NOT touched:
    assert not (tmp_path / "animations" / "scenes.py").exists()


def test_generate_scene_idempotent_second_call_replaces_block(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    v1 = _GOOD_CLASS
    v2 = _GOOD_CLASS.replace("'demo'", "'demo v2'")
    with patch("docgen.scene_generate.call_llm", return_value=v1):
        generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    with patch("docgen.scene_generate.call_llm", return_value=v2):
        generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    out = (tmp_path / "animations" / "scenes.py").read_text(encoding="utf-8")
    assert out.count("BEGIN GENERATED SCENE: 08 (DemoFunctionScene)") == 1
    assert "'demo v2'" in out
    assert "'demo'" not in out.replace("'demo v2'", "")
    import ast
    ast.parse(out)


# ── Pre-write lint (font_size, weight=BOLD, unsafe unicode) ────────────────


def test_lint_passes_clean_block() -> None:
    issues = lint_generated_block(_GOOD_CLASS, min_font_size=14, unsafe_unicode=["\u2192"])
    assert issues == []


def test_lint_flags_small_font_size() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        Text('hi', font_size=12, color=C_RED)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("font_size=12" in i for i in issues)


def test_lint_flags_weight_bold() -> None:
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        "        Text('hi', font_size=20, color=C_ACCENT, weight=BOLD)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=[])
    assert any("weight=BOLD" in i for i in issues)


def test_lint_flags_unsafe_unicode_in_string() -> None:
    # Use real U+2192 in the simulated source; `'\\u2192'` in a .py file is
    # six ASCII chars, not the arrow glyph, so the unicode scan would miss it.
    arrow = chr(0x2192)
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        f"        Text('left {arrow} right', font_size=20, color=C_WHITE)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=["\u2192"])
    assert any("U+2192" in i for i in issues)


def test_lint_flags_unsafe_unicode_in_comment() -> None:
    em_dash = chr(0x2014)
    code = (
        "class A(_TimedScene):\n"
        "    def construct(self):\n"
        f"        # the manifest {em_dash} plus a label\n"
        "        Text('ok', font_size=20, color=C_WHITE)\n"
    )
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=["\u2014"])
    assert any("U+2014" in i for i in issues)


def test_lint_returns_partial_issues_when_unparsable() -> None:
    """Syntax-broken code still surfaces unicode line-scan issues; AST checks bail."""
    arrow = chr(0x2192)
    code = f"Text('x {arrow} y', font_size=12,\n# unbalanced"
    issues = lint_generated_block(code, min_font_size=14, unsafe_unicode=["\u2192"])
    assert any("U+2192" in i for i in issues)


def test_generate_scene_rejects_lint_violation_and_saves_draft(tmp_path: Path) -> None:
    cfg = _setup_project(tmp_path)
    bad = (
        "class DemoFunctionScene(_TimedScene):\n"
        "    def construct(self):\n"
        "        self.camera.background_color = C_BG\n"
        "        Text('OPENAI_API_KEY', font_size=10, color=C_RED)\n"
        "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)\n"
        "        self.timed_wait(0.5)\n"
    )
    with patch("docgen.scene_generate.call_llm", return_value=bad):
        with pytest.raises(SceneGenerationError, match="manim_scene_lint"):
            generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    draft = tmp_path / "animations" / ".scene-generate-drafts" / "08.draft.py"
    assert draft.exists()
    assert "font_size=10" in draft.read_text(encoding="utf-8")
    assert not (tmp_path / "animations" / "scenes.py").exists()


def test_generate_scene_fails_loud_when_narration_missing(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path)
    (tmp_path / "narration").mkdir()
    (tmp_path / "animations").mkdir()
    with patch("docgen.scene_generate.call_llm") as mocked:
        with pytest.raises(SceneGenerationError, match="narration file not found"):
            generate_scene(cfg, "08", extra_paths=[], extra_hints=[])
    mocked.assert_not_called()
