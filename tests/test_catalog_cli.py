"""CLI for docgen catalog."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from docgen.cli import main


def _write_docgen(tmp: Path) -> Path:
    (tmp / "docgen.yaml").write_text(
        yaml.dump({"segments": {"default": ["01"], "all": ["01"]}}),
        encoding="utf-8",
    )
    (tmp / ".git").mkdir()
    return tmp / "docgen.yaml"


def test_catalog_init_writes_file(tmp_path: Path) -> None:
    cfg_path = _write_docgen(tmp_path)
    runner = CliRunner()
    r = runner.invoke(main, ["--config", str(cfg_path), "catalog", "init"])
    assert r.exit_code == 0, r.output
    cat = tmp_path / "docgen.catalog.yaml"
    assert cat.is_file()
    data = yaml.safe_load(cat.read_text(encoding="utf-8"))
    assert data.get("catalog_schema_version") == 1
    assert data.get("entries") == []


def test_catalog_refresh_updates_fingerprints(tmp_path: Path) -> None:
    cfg_path = _write_docgen(tmp_path)
    spec = tmp_path / "tests" / "a.ts"
    spec.parent.mkdir(parents=True)
    spec.write_bytes(b"v1")
    cat = tmp_path / "docgen.catalog.yaml"
    cat.write_text(
        yaml.dump(
            {
                "catalog_schema_version": 1,
                "updated_at": "2000-01-01T00:00:00Z",
                "docgen_version": "0.0.0",
                "entries": [
                    {
                        "id": "e1",
                        "fingerprints": {
                            "tracked_paths": ["tests/a.ts"],
                            "inputs": {},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(main, ["--config", str(cfg_path), "catalog", "refresh"])
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(cat.read_text(encoding="utf-8"))
    inputs = data["entries"][0]["fingerprints"]["inputs"]
    assert inputs.get("tests/a.ts") and len(inputs["tests/a.ts"]) == 64
