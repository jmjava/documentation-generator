"""Tests for Playwright runner command and output path behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from docgen.playwright_runner import PlaywrightError, PlaywrightRunner
from docgen.config import Config


def _write_cfg(tmp_path: Path) -> Config:
    cfg = {
        "dirs": {"terminal": "terminal"},
        "segments": {"default": ["01"], "all": ["01"]},
    }
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


def test_capture_requires_script_or_url(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path)
    runner = PlaywrightRunner(cfg)
    with pytest.raises(PlaywrightError, match="requires --script or --url"):
        runner.capture(script=None, url=None)


def test_capture_runs_script_and_outputs_mp4(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path)
    runner = PlaywrightRunner(cfg)
    script = tmp_path / "capture.py"
    output = cfg.terminal_dir / "rendered" / "demo.mp4"
    script.write_text(
        (
            "import os\n"
            "from pathlib import Path\n"
            "out = Path(os.environ['DOCGEN_PLAYWRIGHT_OUTPUT'])\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_bytes(b'fake-mp4')\n"
        ),
        encoding="utf-8",
    )

    path = runner.capture(script=str(script), source="demo.mp4")
    assert path == output
    assert output.exists()
    assert output.read_bytes() == b"fake-mp4"


def test_capture_builds_env_from_options(tmp_path: Path, monkeypatch) -> None:
    cfg = _write_cfg(tmp_path)
    runner = PlaywrightRunner(cfg)
    script = tmp_path / "capture.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    observed: dict[str, str] = {}

    def _fake_run(cmd, *, cwd, env, capture_output, text, timeout, check):  # noqa: ANN001
        observed["cmd0"] = cmd[0]
        observed["script"] = cmd[1]
        observed["cwd"] = cwd
        observed["url"] = env.get("DOCGEN_PLAYWRIGHT_URL", "")
        observed["viewport"] = env.get("DOCGEN_PLAYWRIGHT_VIEWPORT", "")
        observed["timeout"] = env.get("DOCGEN_PLAYWRIGHT_TIMEOUT_SEC", "")
        out = Path(env["DOCGEN_PLAYWRIGHT_OUTPUT"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("x", encoding="utf-8")

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()

    monkeypatch.setattr("subprocess.run", _fake_run)
    out = runner.capture(
        script=str(script),
        url="http://localhost:3300",
        source="custom.mp4",
        viewport={"width": 1280, "height": 720},
        timeout_sec=45,
    )
    assert out.name == "custom.mp4"
    assert observed["cmd0"] == sys.executable
    assert observed["script"] == str(script.resolve())
    assert observed["cwd"] == str(cfg.base_dir)
    assert observed["url"] == "http://localhost:3300"
    assert observed["viewport"] == "1280x720"
    assert observed["timeout"] == "45"
