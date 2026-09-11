"""CI must run `docgen validate` on a scratch init bundle and be able to go red."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from docgen.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_ci_workflow_requires_docgen_validate() -> None:
    """Future PRs must not drop the named CI job that invokes validate."""
    workflow = ROOT / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "\n  validate:" in text
    assert "docgen validate" in text
    assert "scripts/ci-validate-scratch-bundle.sh" in text
    assert "Validate scratch init bundle" in text
    # Keep the existing benchmark job.
    assert "\n  benchmark:" in text
    assert "docgen benchmark" in text


def test_ci_validate_script_invokes_docgen_validate() -> None:
    script = (ROOT / "scripts" / "ci-validate-scratch-bundle.sh").read_text(encoding="utf-8")
    assert "init --defaults" in script
    assert " validate" in script or "validate " in script
    assert "--pre-push" not in script


def test_scratch_init_bundle_validate_exits_1(tmp_path: Path) -> None:
    """Drop a segment with no recordings; default validate must exit 1."""
    consumer = tmp_path / "app"
    consumer.mkdir()
    (consumer / ".git").mkdir()
    runner = CliRunner()
    init = runner.invoke(main, ["--repo", str(consumer), "init", "--defaults"])
    assert init.exit_code == 0, init.output
    yaml_path = consumer / "docs" / "demos" / "docgen.yaml"
    assert yaml_path.is_file()
    rec_dir = consumer / "docs" / "demos" / "recordings"
    assert rec_dir.is_dir()
    assert not list(rec_dir.glob("*.mp4"))

    result = runner.invoke(main, ["--config", str(yaml_path), "validate"])
    combined = result.output + result.stderr
    assert result.exit_code == 1, combined
    assert "FAIL" in combined
    assert "recording_exists" in combined


def test_ci_validate_scratch_bundle_script(tmp_path: Path) -> None:
    """The CI script itself must stay red-capable (validate exit 1 → script 0)."""
    script = ROOT / "scripts" / "ci-validate-scratch-bundle.sh"
    env = os.environ.copy()
    wrapper = tmp_path / "docgen"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f'export PYTHONPATH={str(ROOT / "src")!r}\n'
        f'exec {sys.executable!r} -m docgen "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env["DOCGEN"] = str(wrapper)
    result = subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "FAIL" in combined
    assert "recording_exists" in combined
    assert "docgen validate exited 1" in combined
