"""Tests for wizard focus-file scan + durable hint persistence."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.config import Config
from docgen.wizard import create_app, scan_repo_files
from docgen.yaml_generate import (
    ensure_segment_hint_with_focus,
    find_hint_path_for_segment,
    read_hint_focus_paths,
    update_hint_focus_paths,
)


def test_scan_repo_files_includes_source_types(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Hello\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "cfg.yaml").write_text("a: 1\n", encoding="utf-8")
    (tmp_path / "skip.bin").write_bytes(b"\x00\x01")

    files = scan_repo_files(tmp_path)
    paths = {f["path"] for f in files}
    assert "README.md" in paths
    assert "src/main.py" in paths
    assert "cfg.yaml" in paths
    assert "skip.bin" not in paths


def test_scan_repo_files_extensions_filter(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("m", encoding="utf-8")
    (tmp_path / "b.py").write_text("p", encoding="utf-8")
    files = scan_repo_files(tmp_path, extensions=(".md",))
    assert [f["path"] for f in files] == ["a.md"]


def _bundle_cfg(tmp_path: Path) -> Config:
    hints = tmp_path / "hints"
    hints.mkdir()
    (hints / "segment-01-topic.md").write_text(
        "---\n"
        "docgen:\n"
        "  segment:\n"
        "    create: true\n"
        "    id: \"01\"\n"
        "    stem: 01-demo\n"
        "  wiring:\n"
        "    narration:\n"
        "      context:\n"
        "        paths:\n"
        "          - README.md\n"
        "---\n\n# Topic\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    raw = {
        "repo_root": ".",
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
            "hints": "hints",
        },
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "manim", "scene": "DemoScene", "source": "DemoScene.mp4"}},
        "discovery": {"auto_visual_map": False, "merge_hint_segments": True},
        "narration_from_source": {
            "segments": {"01": {"context": {"paths": ["README.md"]}}},
        },
    }
    yml = tmp_path / "docgen.yaml"
    yml.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(yml)


def test_update_hint_focus_paths_rewrites_front_matter(tmp_path: Path) -> None:
    cfg = _bundle_cfg(tmp_path)
    hint = find_hint_path_for_segment(cfg.hints_dir, "01")
    assert hint is not None
    written = update_hint_focus_paths(hint, ["README.md", "src/app.py"], also_manim=True)
    assert written == ["README.md", "src/app.py"]
    assert read_hint_focus_paths(cfg.hints_dir, "01") == ["README.md", "src/app.py"]
    doc = yaml.safe_load(hint.read_text(encoding="utf-8").split("---", 2)[1])
    assert doc["docgen"]["wiring"]["manim_scene"]["context"]["paths"] == [
        "README.md",
        "src/app.py",
    ]
    assert "# Topic" in hint.read_text(encoding="utf-8")


def test_ensure_creates_hint_when_missing(tmp_path: Path) -> None:
    hints = tmp_path / "hints"
    hints.mkdir()
    (tmp_path / "notes.md").write_text("n", encoding="utf-8")
    path, written = ensure_segment_hint_with_focus(
        hints, "02", stem="02-new", paths=["notes.md"]
    )
    assert path.name == "segment-02-topic.md"
    assert written == ["notes.md"]
    assert read_hint_focus_paths(hints, "02") == ["notes.md"]


def test_wizard_focus_api_persists(tmp_path: Path) -> None:
    cfg = _bundle_cfg(tmp_path)
    app = create_app(cfg)
    client = app.test_client()

    get_res = client.get("/api/segments/01/focus")
    assert get_res.status_code == 200
    assert get_res.get_json()["paths"] == ["README.md"]

    put_res = client.put(
        "/api/segments/01/focus",
        json={"paths": ["README.md", "src/app.py"], "yaml_generate": True},
    )
    assert put_res.status_code == 200, put_res.get_json()
    body = put_res.get_json()
    assert body["ok"] is True
    assert body["paths"] == ["README.md", "src/app.py"]

    seg_res = client.get("/api/segments")
    segs = seg_res.get_json()["segments"]
    assert segs[0]["focus_paths"] == ["README.md", "src/app.py"]

    # Merged into docgen.yaml narration context.
    raw = yaml.safe_load((tmp_path / "docgen.yaml").read_text(encoding="utf-8"))
    paths = raw["narration_from_source"]["segments"]["01"]["context"]["paths"]
    assert "src/app.py" in paths


def test_wizard_scan_api_returns_extensions(tmp_path: Path) -> None:
    cfg = _bundle_cfg(tmp_path)
    app = create_app(cfg)
    client = app.test_client()
    res = client.get("/api/scan")
    data = res.get_json()
    assert res.status_code == 200
    paths = {f["path"] for f in data["files"]}
    assert "src/app.py" in paths
    assert ".py" in data["extensions"]
