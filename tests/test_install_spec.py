"""Tests for external-install helpers (no vendored library in consumer src)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from docgen.cli import main
from docgen.config import Config
from docgen.install_spec import (
    DOCGEN_PIP_SPEC,
    package_version,
    pip_spec_for_ref,
    read_requirements_pin,
    requirements_docgen_txt,
    tool_info,
    update_docgen_install,
    validate_git_ref,
    write_requirements_docgen,
)
from docgen.wizard import create_app


def test_requirements_docgen_txt_default() -> None:
    text = requirements_docgen_txt()
    assert DOCGEN_PIP_SPEC in text
    assert "pipx install" in text
    assert "uv tool install" in text
    assert "do NOT vendor" in text
    assert "Wizard:" in text


def test_requirements_docgen_txt_pin() -> None:
    text = requirements_docgen_txt(pin_ref="abc1234")
    assert "@abc1234" in text
    assert "Pinned ref: abc1234" in text


def test_validate_git_ref_rejects_shell_meta() -> None:
    with pytest.raises(ValueError):
        validate_git_ref("main; rm -rf /")
    with pytest.raises(ValueError):
        validate_git_ref("../etc/passwd")
    assert validate_git_ref("main") == "main"
    assert validate_git_ref("@deadbeef") == "deadbeef"


def test_pip_spec_for_ref_manim() -> None:
    assert "docgen[manim]" in pip_spec_for_ref("main", with_manim=True)
    assert "@main" in pip_spec_for_ref("main")


def test_write_and_read_requirements_pin(tmp_path: Path) -> None:
    path = write_requirements_docgen(tmp_path, pin_ref="cafe0123")
    assert path.is_file()
    assert read_requirements_pin(path) == "cafe0123"


def test_update_docgen_install_mocked(tmp_path: Path) -> None:
    class _Proc:
        returncode = 0
        stdout = "Successfully installed docgen\n"
        stderr = ""

    with patch("docgen.install_spec.subprocess.run", return_value=_Proc()) as run:
        result = update_docgen_install(
            ref="main",
            bundle_dir=tmp_path,
            update_requirements=True,
        )
    assert result.ok
    assert result.ref == "main"
    assert result.requirements_updated
    assert (tmp_path / "requirements-docgen.txt").is_file()
    assert "documentation-generator.git@main" in run.call_args.args[0][-1]
    assert result.restart_required is True


def test_update_docgen_install_rejects_bad_ref(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        update_docgen_install(ref="main && true", bundle_dir=tmp_path)


def test_cli_version() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["--version"])
    assert r.exit_code == 0, r.output
    assert "docgen" in r.output
    assert DOCGEN_PIP_SPEC in r.output or "documentation-generator.git" in r.output
    assert package_version()  # non-empty


def test_wizard_tool_api(tmp_path: Path) -> None:
    write_requirements_docgen(tmp_path, pin_ref="abcd1234")
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump(
            {
                "dirs": {"narration": "narration"},
                "segments": {"all": ["01"]},
                "segment_names": {"01": "01-x"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "narration").mkdir()
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    app = create_app(cfg)
    client = app.test_client()

    info = client.get("/api/tool")
    assert info.status_code == 200
    body = info.get_json()
    assert body["requirements_pin"] == "abcd1234"
    assert "version" in body

    class _Proc:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    with patch("docgen.install_spec.subprocess.run", return_value=_Proc()):
        upd = client.post(
            "/api/tool/update",
            json={"ref": "main", "update_requirements": True, "with_manim": False},
        )
    assert upd.status_code == 200, upd.get_json()
    data = upd.get_json()
    assert data["ok"] is True
    assert data["restart_required"] is True
    assert read_requirements_pin(tmp_path / "requirements-docgen.txt") == "main"

    bad = client.post("/api/tool/update", json={"ref": "main;id"})
    assert bad.status_code == 400


def test_tool_info_without_requirements(tmp_path: Path) -> None:
    info = tool_info(tmp_path)
    assert info.requirements_path is None
    assert info.requirements_pin is None
    assert info.python
