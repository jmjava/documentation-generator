"""Tests for docgen.pages HTML generation helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.config import Config
from docgen.pages import PagesGenerator, _esc


def test_esc_ampersand():
    assert _esc("A & B") == "A &amp; B"


def test_esc_angle_brackets():
    assert _esc("<script>") == "&lt;script&gt;"


def test_esc_quotes():
    assert _esc('say "hello"') == "say &quot;hello&quot;"


def test_esc_clean():
    assert _esc("Normal text") == "Normal text"


def _write_pages_cfg(tmp_path: Path, pages_cfg: dict) -> Config:
    cfg = {
        "dirs": {
            "animations": "animations",
            "terminal": "terminal",
            "audio": "audio",
            "recordings": "recordings",
        },
        "segments": {"default": [], "all": []},
        "segment_names": {},
        "visual_map": {},
        "pages": pages_cfg,
    }
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


def test_index_html_omits_per_function_section_when_unconfigured(tmp_path: Path) -> None:
    cfg = _write_pages_cfg(
        tmp_path,
        {"title": "Demos", "subtitle": "x", "demos_subdir": "demos", "segments": {}},
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Per-function videos" not in html
    assert "<h2 class=\"section-title\">Segments</h2>" in html
    assert "<h2 class=\"section-title\">Full demos</h2>" in html


def test_index_html_renders_per_function_card(tmp_path: Path) -> None:
    cfg = _write_pages_cfg(
        tmp_path,
        {
            "title": "Demos",
            "subtitle": "x",
            "demos_subdir": "demos",
            "segments": {},
            "per_function": {
                "lesson-compile": {
                    "title": "Per-function: lesson compile",
                    "description": "Rendered by docgen demo-function.",
                    "source": "recordings/per-function/lesson-compile.mp4",
                    "poster": "recordings/per-function/lesson-compile.poster.png",
                    "manifest": "per-function/lesson-compile.docgen.yaml",
                }
            },
        },
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Per-function videos" in html
    assert 'id="pf-lesson-compile"' in html
    assert "Per-function: lesson compile" in html
    assert 'src="demos/recordings/per-function/lesson-compile.mp4"' in html
    assert 'poster="demos/recordings/per-function/lesson-compile.poster.png"' in html
    assert 'href="demos/per-function/lesson-compile.docgen.yaml"' in html
    assert "section-blurb" in html


def test_index_html_per_function_escapes_user_strings(tmp_path: Path) -> None:
    cfg = _write_pages_cfg(
        tmp_path,
        {
            "title": "Demos",
            "subtitle": "x",
            "demos_subdir": "demos",
            "segments": {},
            "per_function": {
                "evil": {
                    "title": "<script>alert(1)</script>",
                    "description": "A & B",
                    "source": "recordings/per-function/evil.mp4",
                }
            },
        },
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)" not in html
    assert "A &amp; B" in html
