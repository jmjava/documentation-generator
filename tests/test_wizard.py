"""Tests for docgen.wizard file scanning and tree building."""


from docgen.wizard import scan_md_files, build_file_tree


def test_scan_md_files(tmp_path):
    (tmp_path / "README.md").write_text("# Hello\nWorld", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("Guide content", encoding="utf-8")
    (tmp_path / "other.txt").write_text("Not markdown", encoding="utf-8")

    files = scan_md_files(tmp_path)
    paths = [f["path"] for f in files]
    assert "README.md" in paths
    assert "docs/guide.md" in paths
    assert "other.txt" not in paths


def test_scan_respects_excludes(tmp_path):
    (tmp_path / "README.md").write_text("Hello", encoding="utf-8")
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "old.md").write_text("Old", encoding="utf-8")

    files = scan_md_files(tmp_path, exclude_patterns=["**/archive/**"])
    paths = [f["path"] for f in files]
    assert "README.md" in paths
    assert "archive/old.md" not in paths


def test_scan_skips_dotgit(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.md").write_text("git internal", encoding="utf-8")
    (tmp_path / "real.md").write_text("Real file", encoding="utf-8")

    files = scan_md_files(tmp_path)
    paths = [f["path"] for f in files]
    assert "real.md" in paths
    assert ".git/config.md" not in paths


def test_build_file_tree():
    files = [
        {"path": "README.md", "snippet": "Hello"},
        {"path": "docs/guide.md", "snippet": "Guide"},
        {"path": "docs/api.md", "snippet": "API"},
    ]
    tree = build_file_tree(files)
    assert any(n["name"] == "README.md" for n in tree)
    docs = next(n for n in tree if n["name"] == "docs")
    assert docs["type"] == "dir"
    assert len(docs["children"]) == 2


def test_snippet_populated(tmp_path):
    (tmp_path / "test.md").write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5", encoding="utf-8")
    files = scan_md_files(tmp_path)
    assert files[0]["snippet"].startswith("Line 1")
