"""Tests for docgen.source_catalog."""

from __future__ import annotations

from pathlib import Path

from docgen.source_catalog import (
    clear_regenerate_pin,
    entry_needs_regeneration,
    entry_should_run,
    force_ids_from_env,
    global_force_from_env,
    parse_force_id_list,
    refresh_entry_fingerprints,
)


def _entry_with_fingerprints(repo: Path, rel: str, content: bytes) -> dict:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return {
        "id": "e1",
        "fingerprints": {
            "tracked_paths": [rel],
            "inputs": {},  # filled by refresh
        },
    }


def test_entry_needs_regeneration_when_inputs_match(tmp_path: Path) -> None:
    repo = tmp_path
    entry = _entry_with_fingerprints(repo, "spec/a.ts", b"v1")
    refresh_entry_fingerprints(entry, repo)
    assert entry_needs_regeneration(entry, repo, force=False) is False


def test_entry_needs_regeneration_when_file_changes(tmp_path: Path) -> None:
    repo = tmp_path
    entry = _entry_with_fingerprints(repo, "spec/a.ts", b"v1")
    refresh_entry_fingerprints(entry, repo)
    (repo / "spec" / "a.ts").write_bytes(b"v2")
    assert entry_needs_regeneration(entry, repo, force=False) is True


def test_parse_force_id_list() -> None:
    assert parse_force_id_list(None) == set()
    assert parse_force_id_list("") == set()
    assert parse_force_id_list(" a , b ") == {"a", "b"}


def test_entry_should_run_force_ids(tmp_path: Path) -> None:
    repo = tmp_path
    entry = _entry_with_fingerprints(repo, "spec/a.ts", b"v1")
    refresh_entry_fingerprints(entry, repo)
    assert entry_should_run(entry, repo, global_force=False, force_ids={"e1"}) is True
    assert entry_should_run(entry, repo, global_force=False, force_ids={"other"}) is False


def test_entry_should_run_regenerate_pin(tmp_path: Path) -> None:
    repo = tmp_path
    entry = _entry_with_fingerprints(repo, "spec/a.ts", b"v1")
    refresh_entry_fingerprints(entry, repo)
    entry["policy"] = {"regenerate": True}
    assert entry_should_run(entry, repo) is True


def test_clear_regenerate_pin_policy(tmp_path: Path) -> None:
    entry = {"id": "e1", "policy": {"regenerate": True}}
    assert clear_regenerate_pin(entry) is True
    assert entry["policy"]["regenerate"] is False


def test_force_ids_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DOCGEN_CATALOG_FORCE_IDS", "x,y")
    assert force_ids_from_env() == {"x", "y"}
    monkeypatch.delenv("DOCGEN_CATALOG_FORCE_IDS", raising=False)
    assert force_ids_from_env() == set()


def test_global_force_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DOCGEN_CATALOG_FORCE_ALL", "1")
    assert global_force_from_env() is True
    monkeypatch.setenv("DOCGEN_CATALOG_FORCE_ALL", "false")
    assert global_force_from_env() is False
    monkeypatch.delenv("DOCGEN_CATALOG_FORCE_ALL", raising=False)
    assert global_force_from_env() is False
