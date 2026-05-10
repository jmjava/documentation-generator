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
