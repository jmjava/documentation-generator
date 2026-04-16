"""Tests for docgen.chat — interactive chat interface."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
import yaml

from docgen.chat import _build_context, _handle_slash_command, run_chat
from docgen.config import Config


@pytest.fixture
def chat_config(tmp_path):
    cfg_data = {
        "segments": {"all": ["01", "02"]},
        "segment_names": {"01": "01-overview", "02": "02-setup"},
        "visual_map": {"01": {"type": "manim"}, "02": {"type": "vhs"}},
    }
    for d in ("narration", "audio", "recordings", "animations", "terminal"):
        (tmp_path / d).mkdir()
    (tmp_path / "narration" / "01-overview.md").write_text("Hello narration", encoding="utf-8")
    (tmp_path / "audio" / "01-overview.mp3").write_bytes(b"fake audio")

    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg_data), encoding="utf-8")
    return Config.from_yaml(p)


class TestBuildContext:
    def test_includes_segments(self, chat_config):
        ctx = _build_context(chat_config)
        assert "01" in ctx
        assert "02" in ctx
        assert "01-overview" in ctx

    def test_includes_file_counts(self, chat_config):
        ctx = _build_context(chat_config)
        assert "Narration files: 1" in ctx
        assert "Audio files: 1" in ctx

    def test_none_config(self):
        assert _build_context(None) == ""


class TestSlashCommands:
    def test_quit(self):
        assert _handle_slash_command("/quit", None, []) is False

    def test_exit(self):
        assert _handle_slash_command("/exit", None, []) is False

    def test_help(self, capsys):
        assert _handle_slash_command("/help", None, []) is True
        captured = capsys.readouterr()
        assert "/help" in captured.out

    def test_status_no_config(self, capsys):
        assert _handle_slash_command("/status", None, []) is True
        captured = capsys.readouterr()
        assert "No docgen.yaml" in captured.out

    def test_status_with_config(self, chat_config, capsys):
        assert _handle_slash_command("/status", chat_config, []) is True
        captured = capsys.readouterr()
        assert "01" in captured.out
        assert "02" in captured.out

    def test_clear(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        assert _handle_slash_command("/clear", None, history) is True
        assert len(history) == 1
        assert history[0]["role"] == "system"

    def test_unknown_command(self, capsys):
        assert _handle_slash_command("/foo", None, []) is True
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out


class TestRunChatNonInteractive:
    def test_non_interactive_mode(self, chat_config):
        mock_provider = MagicMock()
        mock_provider.chat.return_value = "Generated narration for segment 01."

        with patch("sys.stdin", StringIO("generate narration for segment 01")):
            run_chat(
                chat_config,
                mock_provider,
                non_interactive=True,
            )

        mock_provider.chat.assert_called_once()
        call_kwargs = mock_provider.chat.call_args.kwargs
        messages = call_kwargs["messages"]
        assert any("generate narration" in m["content"] for m in messages if m["role"] == "user")

    def test_non_interactive_empty_stdin(self, chat_config):
        mock_provider = MagicMock()
        with patch("sys.stdin", StringIO("")):
            run_chat(chat_config, mock_provider, non_interactive=True)
        mock_provider.chat.assert_not_called()
