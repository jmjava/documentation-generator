"""Tests for CLI env_file loading (issue #55 UX)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from docgen import cli
from docgen.config import Config


def _minimal_cfg(tmp_path: Path, **extra: object) -> Config:
    raw = {
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "visual_map": {"01": {"type": "still", "source": "01.mp4"}},
        **extra,
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(p)


def test_load_env_warns_when_openai_in_shell_and_env_file(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-file\n", encoding="utf-8")
    cfg = _minimal_cfg(tmp_path, env_file=".env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
    monkeypatch.delenv("DOCGEN_ENV_OVERRIDES", raising=False)

    cli._load_env(cfg)

    err = capsys.readouterr().err
    assert "OPENAI_API_KEY already set" in err
    assert os.environ["OPENAI_API_KEY"] == "sk-from-shell"


def test_load_env_warns_when_xai_in_shell_and_env_file(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / ".env").write_text("XAI_API_KEY=xai-from-file\n", encoding="utf-8")
    cfg = _minimal_cfg(tmp_path, env_file=".env")
    monkeypatch.setenv("XAI_API_KEY", "xai-from-shell")
    monkeypatch.delenv("DOCGEN_ENV_OVERRIDES", raising=False)

    cli._load_env(cfg)

    err = capsys.readouterr().err
    assert "XAI_API_KEY already set" in err
    assert os.environ["XAI_API_KEY"] == "xai-from-shell"


def test_load_env_docgen_env_overrides_all(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-file\nOTHER=x\n", encoding="utf-8")
    cfg = _minimal_cfg(tmp_path, env_file=".env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
    monkeypatch.setenv("DOCGEN_ENV_OVERRIDES", "1")

    cli._load_env(cfg)

    assert os.environ["OPENAI_API_KEY"] == "sk-from-file"
    assert os.environ["OTHER"] == "x"


def test_load_env_docgen_env_overrides_selected_keys(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-from-file\nKEEP_ME=from-file\n",
        encoding="utf-8",
    )
    cfg = _minimal_cfg(tmp_path, env_file=".env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
    monkeypatch.setenv("KEEP_ME", "from-shell")
    monkeypatch.setenv("DOCGEN_ENV_OVERRIDES", "OPENAI_API_KEY")

    cli._load_env(cfg)

    assert os.environ["OPENAI_API_KEY"] == "sk-from-file"
    assert os.environ["KEEP_ME"] == "from-shell"


def test_ai_status_exits_zero_when_cursor_key_present(
    tmp_path: Path, monkeypatch
) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    monkeypatch.setenv("CURSOR_API_KEY", "sk-proj-test")
    monkeypatch.delenv("DOCGEN_AI_PROVIDER", raising=False)
    cfg = _minimal_cfg(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(cfg.yaml_path), "ai-status"])
    assert result.exit_code == 0, result.output
    assert "provider=openai" in result.output
    assert "CURSOR_API_KEY=present" in result.output
    assert "not tied to one IDE" in result.output
