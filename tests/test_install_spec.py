"""Tests for external-install helpers (no vendored library in consumer src)."""

from __future__ import annotations

from click.testing import CliRunner

from docgen.cli import main
from docgen.install_spec import (
    DOCGEN_PIP_SPEC,
    package_version,
    requirements_docgen_txt,
)


def test_requirements_docgen_txt_default() -> None:
    text = requirements_docgen_txt()
    assert DOCGEN_PIP_SPEC in text
    assert "pipx install" in text
    assert "uv tool install" in text
    assert "do NOT vendor" in text


def test_requirements_docgen_txt_pin() -> None:
    text = requirements_docgen_txt(pin_ref="abc1234")
    assert "@abc1234" in text
    assert "Pinned ref: abc1234" in text


def test_cli_version() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["--version"])
    assert r.exit_code == 0, r.output
    assert "docgen" in r.output
    assert DOCGEN_PIP_SPEC in r.output or "documentation-generator.git" in r.output
    # package_version is best-effort when running from source tree
    assert package_version()  # non-empty
