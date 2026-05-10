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


def _write_pages_cfg(
    tmp_path: Path,
    pages_cfg: dict,
    *,
    segments_all: list[str] | None = None,
    segment_names: dict[str, str] | None = None,
) -> Config:
    seg_all = segments_all if segments_all is not None else []
    cfg = {
        "dirs": {
            "animations": "animations",
            "audio": "audio",
            "recordings": "recordings",
        },
        "segments": {"default": seg_all, "all": seg_all},
        "segment_names": segment_names or {},
        "visual_map": {},
        "pages": pages_cfg,
    }
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


def test_index_html_renders_section_headers(tmp_path: Path) -> None:
    cfg = _write_pages_cfg(
        tmp_path,
        {"title": "Demos", "subtitle": "x", "demos_subdir": "demos", "segments": {}},
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<h2 class=\"section-title\">Segments</h2>" in html
    assert "<h2 class=\"section-title\">Full demos</h2>" in html


def test_index_html_segments_discovered_from_segment_names_when_pages_empty(tmp_path: Path) -> None:
    """When ``pages.segments`` is missing/empty, fall back to ``segments.all`` + ``segment_names``."""
    cfg = _write_pages_cfg(
        tmp_path,
        {"title": "Demos", "subtitle": "x", "demos_subdir": "demos"},
        segments_all=["01", "05"],
        segment_names={"01": "01-overview", "05": "05-architecture"},
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'id="seg-01"' in html
    assert "01 — Overview" in html
    assert 'id="seg-05"' in html
    assert "05 — Architecture" in html


def test_index_html_explicit_pages_segments_override_discovery(tmp_path: Path) -> None:
    """Maintainer-authored ``pages.segments`` titles still win over discovery defaults."""
    cfg = _write_pages_cfg(
        tmp_path,
        {
            "title": "Demos",
            "subtitle": "x",
            "demos_subdir": "demos",
            "segments": {"01": {"title": "Architecture Overview", "description": "Hand-written copy."}},
        },
        segments_all=["01"],
        segment_names={"01": "01-overview"},
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "01 — Architecture Overview" in html
    assert "Hand-written copy." in html
    assert "01 — Overview<" not in html


def test_index_html_segment_titles_escape_user_strings(tmp_path: Path) -> None:
    cfg = _write_pages_cfg(
        tmp_path,
        {
            "title": "Demos",
            "subtitle": "x",
            "demos_subdir": "demos",
            "segments": {
                "01": {"title": "<script>alert(1)</script>", "description": "A & B"},
            },
        },
        segments_all=["01"],
        segment_names={"01": "01-overview"},
    )
    PagesGenerator(cfg).generate_index_html(force=True)
    html = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)" not in html
    assert "A &amp; B" in html
