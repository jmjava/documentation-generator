"""Tests for docgen.wizard file scanning and tree building."""

import pytest

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


def test_load_state_rejects_non_object_segments(tmp_path):
    import json

    from docgen.wizard import WizardError, load_state

    (tmp_path / ".docgen-state.json").write_text(
        json.dumps({"segments": ["01"]}), encoding="utf-8"
    )
    with pytest.raises(WizardError, match=r"\.docgen-state.json segments must be a JSON object, not list"):
        load_state(tmp_path)


def test_load_state_rejects_non_object_segment_row(tmp_path):
    import json

    from docgen.wizard import WizardError, load_state

    (tmp_path / ".docgen-state.json").write_text(
        json.dumps({"segments": {"01": "draft"}}), encoding="utf-8"
    )
    with pytest.raises(
        WizardError,
        match=r"\.docgen-state.json segments\['01'\] must be a JSON object, not str",
    ):
        load_state(tmp_path)


def test_load_state_null_segments_is_empty(tmp_path):
    import json

    from docgen.wizard import load_state

    (tmp_path / ".docgen-state.json").write_text(
        json.dumps({"segments": None, "extra": 1}), encoding="utf-8"
    )
    assert load_state(tmp_path) == {"segments": {}, "extra": 1}


def _wizard_client(tmp_path):
    from docgen.config import Config
    from docgen.wizard import create_app

    yaml_path = tmp_path / "docgen.yaml"
    yaml_path.write_text(
        "repo_root: .\nsegments:\n  default: ['01']\n  all: ['01']\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(yaml_path)
    return create_app(cfg).test_client(), cfg


def test_api_segments_rejects_list_state_segments(tmp_path):
    import json

    client, cfg = _wizard_client(tmp_path)
    (cfg.base_dir / ".docgen-state.json").write_text(
        json.dumps({"segments": []}), encoding="utf-8"
    )
    res = client.get("/api/segments")
    assert res.status_code == 500
    assert "segments must be a JSON object" in res.get_json()["error"]


def test_api_state_post_rejects_list_body(tmp_path):
    client, _cfg = _wizard_client(tmp_path)
    res = client.post("/api/state", json=["not", "an", "object"])
    assert res.status_code == 400
    assert res.get_json()["error"] == "request body must be a JSON object, not list"


def test_api_state_post_rejects_list_segments(tmp_path):
    client, cfg = _wizard_client(tmp_path)
    res = client.post("/api/state", json={"segments": ["01"]})
    assert res.status_code == 400
    assert "segments must be a JSON object" in res.get_json()["error"]
    assert not (cfg.base_dir / ".docgen-state.json").exists()


def test_api_state_roundtrip_object_segments(tmp_path):
    client, cfg = _wizard_client(tmp_path)
    payload = {"segments": {"01": {"status": "ready", "revision_notes": "n"}}}
    res = client.post("/api/state", json=payload)
    assert res.status_code == 200
    got = client.get("/api/state")
    assert got.status_code == 200
    assert got.get_json()["segments"]["01"]["status"] == "ready"
    segs = client.get("/api/segments")
    assert segs.status_code == 200
    assert segs.get_json()["segments"][0]["status"] == "ready"
    assert (cfg.base_dir / ".docgen-state.json").is_file()


def test_api_post_rejects_list_json_bodies(tmp_path):
    client, _cfg = _wizard_client(tmp_path)
    endpoints = (
        ("POST", "/api/open-bundle"),
        ("POST", "/api/tool/update"),
        ("POST", "/api/generate-narration"),
        ("POST", "/api/run-from/tts/01"),
        ("PUT", "/api/narration/01"),
        ("PUT", "/api/segments/01/focus"),
    )
    for method, path in endpoints:
        res = client.open(path, method=method, json=["not", "an", "object"])
        assert res.status_code == 400, path
        assert res.get_json()["error"] == "request body must be a JSON object, not list"


def test_api_tool_update_rejects_string_with_manim(tmp_path):
    client, _cfg = _wizard_client(tmp_path)
    res = client.post("/api/tool/update", json={"with_manim": "false"})
    assert res.status_code == 400
    assert "with_manim must be a JSON boolean" in res.get_json()["error"]


def test_api_run_from_rejects_string_llm_scene_spec(tmp_path):
    client, _cfg = _wizard_client(tmp_path)
    res = client.post("/api/run-from/tts/01", json={"llm_scene_spec": "true"})
    assert res.status_code == 400
    assert "llm_scene_spec must be a JSON boolean" in res.get_json()["error"]


def test_api_put_focus_rejects_string_yaml_generate(tmp_path):
    client, _cfg = _wizard_client(tmp_path)
    res = client.put(
        "/api/segments/01/focus",
        json={"paths": ["README.md"], "yaml_generate": "true"},
    )
    assert res.status_code == 400
    assert "yaml_generate must be a JSON boolean" in res.get_json()["error"]



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


def test_generate_narration_rejects_escaped_source_path(tmp_path):
    from docgen.config import Config
    from docgen.wizard import create_app

    repo = tmp_path / "proj"
    evil = tmp_path / "secret.md"
    repo.mkdir()
    evil.write_text("leak", encoding="utf-8")
    yaml_path = repo / "docgen.yaml"
    yaml_path.write_text(
        "repo_root: .\nsegments:\n  default: ['01']\n  all: ['01']\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(yaml_path)
    client = create_app(cfg).test_client()
    resp = client.post(
        "/api/generate-narration",
        json={
            "segment_name": "01-intro",
            "source_paths": ["../secret.md"],
            "guidance": "x",
        },
    )
    assert resp.status_code == 400
    assert "invalid path" in resp.get_json()["error"]


def test_generate_narration_rejects_missing_source_path(tmp_path):
    from docgen.config import Config
    from docgen.wizard import create_app

    repo = tmp_path / "proj"
    repo.mkdir()
    yaml_path = repo / "docgen.yaml"
    yaml_path.write_text(
        "repo_root: .\nsegments:\n  default: ['01']\n  all: ['01']\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(yaml_path)
    client = create_app(cfg).test_client()
    resp = client.post(
        "/api/generate-narration",
        json={
            "segment_id": "01",
            "segment_name": "01-intro",
            "source_paths": ["missing.md"],
            "guidance": "x",
        },
    )
    assert resp.status_code == 400
    assert "file not found" in resp.get_json()["error"]


def test_generate_narration_requires_sources_in_generate_mode(tmp_path, monkeypatch):
    from docgen.config import Config
    from docgen.wizard import create_app

    repo = tmp_path / "proj"
    repo.mkdir()
    yaml_path = repo / "docgen.yaml"
    yaml_path.write_text(
        "repo_root: .\nsegments:\n  default: ['01']\n  all: ['01']\n",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(yaml_path)
    called = {"n": 0}

    def boom(**_kwargs):
        called["n"] += 1
        return "should not run"

    monkeypatch.setattr("docgen.wizard.generate_narration_via_llm", boom)
    client = create_app(cfg).test_client()
    resp = client.post(
        "/api/generate-narration",
        json={
            "segment_id": "01",
            "segment_name": "01-intro",
            "mode": "generate",
            "source_paths": [],
        },
    )
    assert resp.status_code == 400
    assert "source" in resp.get_json()["error"]
    assert called["n"] == 0


def test_generate_narration_via_llm_generate_requires_sources() -> None:
    from docgen.wizard import generate_narration_via_llm

    with pytest.raises(ValueError, match="source documentation"):
        generate_narration_via_llm(
            source_texts=[],
            guidance="",
            system_prompt="x",
            model="gpt-4o",
            segment_name="01",
            mode="generate",
        )
