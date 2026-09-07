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


def test_load_state_corrupt_json_returns_empty(tmp_path):
    from docgen.wizard import load_state

    (tmp_path / ".docgen-state.json").write_text("{not json", encoding="utf-8")
    assert load_state(tmp_path) == {"segments": {}}


def test_api_file_rejects_prefix_escape(tmp_path):
    from docgen.config import Config
    from docgen.wizard import create_app

    repo = tmp_path / "proj"
    evil = tmp_path / "proj-evil"
    repo.mkdir()
    evil.mkdir()
    (evil / "secret.md").write_text("leak", encoding="utf-8")
    (repo / "ok.md").write_text("safe", encoding="utf-8")
    yaml_path = repo / "docgen.yaml"
    yaml_path.write_text(
        "repo_root: .\nsegments:\n  default: ['01']\n  all: ['01']\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(yaml_path)
    client = create_app(cfg).test_client()
    ok = client.get("/api/file", query_string={"path": "ok.md"})
    assert ok.status_code == 200
    assert ok.get_json()["content"] == "safe"
    escaped = client.get("/api/file", query_string={"path": "../proj-evil/secret.md"})
    assert escaped.status_code == 404
