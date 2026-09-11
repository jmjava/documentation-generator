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


def test_tts_without_bundle_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--config", str(tmp_path / "missing.yaml"), "tts", "--dry-run"],
    )
    assert result.exit_code != 0
    assert "docgen.yaml" in (result.output + result.stderr)
    assert "AttributeError" not in (result.output + result.stderr)
    assert result.exception is None or not isinstance(result.exception, AttributeError)


def test_cli_generate_all_empty_segments_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    raw = {
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
        },
        "segments": {"default": ["01"], "all": []},
        "visual_map": {},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--config",
            str(p),
            "generate-all",
            "--skip-tts",
            "--skip-manim",
            "--skip-scene-retime",
        ],
    )
    assert result.exit_code != 0
    assert "segments.all is empty" in (result.output + result.stderr)
    assert not isinstance(result.exception, RuntimeError)


def test_cli_generate_all_does_not_swallow_systemexit(
    tmp_path: Path, monkeypatch
) -> None:
    from click.testing import CliRunner

    from docgen.cli import main
    from docgen.pipeline import Pipeline

    def boom(self, **_kwargs):  # noqa: ANN001
        raise SystemExit(1)

    monkeypatch.setattr(Pipeline, "run", boom)
    cfg = _minimal_cfg(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--config",
            str(cfg.yaml_path),
            "generate-all",
            "--skip-tts",
            "--skip-manim",
            "--skip-scene-retime",
        ],
    )
    assert result.exit_code == 1


def test_cli_invalid_yaml_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    p = tmp_path / "docgen.yaml"
    p.write_text("segments: [\n  unclosed\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(p), "lint"])
    assert result.exit_code != 0
    combined = result.output + result.stderr
    assert "valid YAML" in combined
    assert "Traceback" not in combined
    assert not isinstance(result.exception, yaml.YAMLError)


def test_cli_list_root_yaml_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    p = tmp_path / "docgen.yaml"
    p.write_text("- not a mapping\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(p), "yaml-generate", "--dry-run"])
    assert result.exit_code != 0
    combined = result.output + result.stderr
    assert "mapping" in combined
    assert "AttributeError" not in combined


def test_cli_list_dirs_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    p = tmp_path / "docgen.yaml"
    p.write_text("dirs: [narration]\nsegments:\n  all: [\"01\"]\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(p), "lint"])
    assert result.exit_code != 0
    combined = result.output + result.stderr
    assert "dirs must be a YAML mapping" in combined
    assert "AttributeError" not in combined
    assert "Traceback" not in combined


def test_cli_validate_help_lists_contract_flags() -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    result = CliRunner().invoke(main, ["validate", "--help"])
    assert result.exit_code == 0, result.output
    assert "--pre-push" in result.output
    assert "--max-drift" in result.output


def test_cli_validate_without_bundle_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--config", str(tmp_path / "missing.yaml"), "validate"],
    )
    assert result.exit_code != 0
    combined = result.output + result.stderr
    assert "docgen.yaml" in combined
    assert "AttributeError" not in combined
    assert "Traceback" not in combined
    assert result.exception is None or not isinstance(result.exception, AttributeError)


def test_cli_validate_pre_push_missing_recording_is_soft(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    raw = {
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-intro"},
        "visual_map": {"01": {"type": "still", "source": "01.mp4"}},
    }
    yaml_path = tmp_path / "docgen.yaml"
    yaml_path.write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "narration").mkdir()
    (tmp_path / "narration" / "01-intro.md").write_text(
        "This segment is a short still-image intro.\n",
        encoding="utf-8",
    )
    for name in ("audio", "animations", "recordings"):
        (tmp_path / name).mkdir()

    result = CliRunner().invoke(main, ["--config", str(yaml_path), "validate", "--pre-push"])
    combined = result.output + result.stderr
    assert result.exit_code == 0, combined
    assert "All checks passed" in combined
    assert "WARN" in combined and "recording_exists" in combined
    assert "WARN" in combined and "timing_sync" in combined
    assert "FAIL" not in combined
    assert "AttributeError" not in combined
    assert "Traceback" not in combined


def test_cli_validate_default_fail_exits_1(tmp_path: Path) -> None:
    """Click-invoke default validate (no --pre-push) must exit 1 on FAIL."""
    from click.testing import CliRunner

    from docgen.cli import main

    raw = {
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-intro"},
        "visual_map": {"01": {"type": "still", "source": "01.mp4"}},
    }
    yaml_path = tmp_path / "docgen.yaml"
    yaml_path.write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "narration").mkdir()
    (tmp_path / "narration" / "01-intro.md").write_text(
        "This segment is a short still-image intro.\n",
        encoding="utf-8",
    )
    for name in ("audio", "animations", "recordings"):
        (tmp_path / name).mkdir()

    result = CliRunner().invoke(main, ["--config", str(yaml_path), "validate"])
    combined = result.output + result.stderr
    assert result.exit_code == 1, combined
    assert "FAIL" in combined
    assert "recording_exists" in combined
    assert "AttributeError" not in combined
    assert "Traceback" not in combined


def test_cli_lint_empty_segments_is_click_error(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    p = tmp_path / "docgen.yaml"
    p.write_text(
        yaml.dump(
            {
                "dirs": {"narration": "narration"},
                "segments": {"all": [], "default": []},
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(p), "lint"])
    assert result.exit_code != 0
    assert "segments.all is empty" in (result.output + result.stderr)
