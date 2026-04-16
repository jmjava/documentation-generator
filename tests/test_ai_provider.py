"""Tests for docgen.ai_provider — provider abstraction layer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from docgen.ai_provider import (
    AIProvider,
    AIProviderError,
    HybridProvider,
    OllamaProvider,
    OpenAIProvider,
    get_provider,
)
from docgen.config import Config


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    def test_is_ai_provider(self):
        p = OpenAIProvider()
        assert isinstance(p, AIProvider)

    def test_chat_calls_openai(self):
        p = OpenAIProvider(default_chat_model="test-model")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from AI"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(p, "_client", return_value=mock_client):
            result = p.chat(messages=[{"role": "user", "content": "hi"}])

        assert result == "Hello from AI"
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "test-model"

    def test_chat_uses_explicit_model(self):
        p = OpenAIProvider(default_chat_model="fallback-model")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "ok"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(p, "_client", return_value=mock_client):
            p.chat(messages=[{"role": "user", "content": "hi"}], model="explicit-model")

        call_kwargs = mock_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["model"] == "explicit-model"

    def test_tts_calls_openai(self, tmp_path):
        p = OpenAIProvider(default_tts_model="tts-model", default_tts_voice="echo")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_client.audio.speech.create.return_value = mock_response

        out_path = tmp_path / "test.mp3"
        with patch.object(p, "_client", return_value=mock_client):
            result = p.tts(text="Hello", output_path=out_path, instructions="Be calm")

        assert result == out_path
        mock_response.stream_to_file.assert_called_once_with(str(out_path))
        call_kwargs = mock_client.audio.speech.create.call_args
        assert call_kwargs.kwargs["model"] == "tts-model"
        assert call_kwargs.kwargs["voice"] == "echo"
        assert call_kwargs.kwargs["instructions"] == "Be calm"

    def test_transcribe_calls_openai(self, tmp_path):
        p = OpenAIProvider(default_whisper_model="whisper-test")
        mock_client = MagicMock()

        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 1.5
        mock_segment.text = "Hello world"

        mock_word = MagicMock()
        mock_word.start = 0.0
        mock_word.end = 0.5
        mock_word.word = "Hello"

        mock_result = MagicMock()
        mock_result.text = "Hello world"
        mock_result.segments = [mock_segment]
        mock_result.words = [mock_word]
        mock_client.audio.transcriptions.create.return_value = mock_result

        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake audio")

        with patch.object(p, "_client", return_value=mock_client):
            result = p.transcribe(
                audio_path=audio_file,
                timestamp_granularities=["word", "segment"],
            )

        assert result["text"] == "Hello world"
        assert len(result["segments"]) == 1
        assert result["segments"][0]["start"] == 0.0
        assert len(result["words"]) == 1
        assert result["words"][0]["word"] == "Hello"


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    def test_tts_raises(self):
        p = OllamaProvider()
        with pytest.raises(AIProviderError, match="Ollama does not support TTS"):
            p.tts(text="hi", output_path="/tmp/out.mp3")

    def test_transcribe_raises(self):
        p = OllamaProvider()
        with pytest.raises(AIProviderError, match="Ollama does not support transcription"):
            p.transcribe(audio_path="/tmp/test.mp3")

    def test_chat_calls_ollama_api(self):
        p = OllamaProvider(url="http://localhost:11434", default_model="test-llm")

        response_body = json.dumps({
            "message": {"role": "assistant", "content": "Hello from Ollama"},
        }).encode()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = response_body
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = p.chat(messages=[{"role": "user", "content": "hi"}])

        assert result == "Hello from Ollama"


# ---------------------------------------------------------------------------
# HybridProvider
# ---------------------------------------------------------------------------


class TestHybridProvider:
    def test_routes_to_correct_providers(self):
        chat_mock = MagicMock()
        chat_mock.chat.return_value = "from chat"

        tts_mock = MagicMock()
        tts_mock.tts.return_value = Path("/tmp/out.mp3")

        transcribe_mock = MagicMock()
        transcribe_mock.transcribe.return_value = {"text": "hello"}

        hybrid = HybridProvider(
            chat_provider=chat_mock,
            tts_provider=tts_mock,
            transcribe_provider=transcribe_mock,
        )

        assert hybrid.chat(messages=[]) == "from chat"
        assert hybrid.tts(text="hi", output_path="/tmp/out.mp3") == Path("/tmp/out.mp3")
        assert hybrid.transcribe(audio_path="/tmp/test.mp3") == {"text": "hello"}

        chat_mock.chat.assert_called_once()
        tts_mock.tts.assert_called_once()
        transcribe_mock.transcribe.assert_called_once()


# ---------------------------------------------------------------------------
# get_provider factory
# ---------------------------------------------------------------------------


class TestGetProvider:
    def _make_config(self, tmp_path: Path, ai_cfg: dict | None = None) -> Config:
        raw = {"segments": {"all": ["01"]}}
        if ai_cfg:
            raw["ai"] = ai_cfg
        p = tmp_path / "docgen.yaml"
        p.write_text(yaml.dump(raw), encoding="utf-8")
        return Config.from_yaml(p)

    def test_default_is_openai(self, tmp_path):
        cfg = self._make_config(tmp_path)
        provider = get_provider(cfg)
        assert isinstance(provider, OpenAIProvider)

    def test_explicit_openai(self, tmp_path):
        cfg = self._make_config(tmp_path, {"provider": "openai"})
        provider = get_provider(cfg)
        assert isinstance(provider, OpenAIProvider)

    def test_ollama_returns_hybrid(self, tmp_path):
        cfg = self._make_config(tmp_path, {"provider": "ollama"})
        provider = get_provider(cfg)
        assert isinstance(provider, HybridProvider)

    def test_env_override(self, tmp_path, monkeypatch):
        cfg = self._make_config(tmp_path, {"provider": "openai"})
        monkeypatch.setenv("DOCGEN_AI_PROVIDER", "ollama")
        provider = get_provider(cfg)
        assert isinstance(provider, HybridProvider)

    def test_unknown_provider_falls_back(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, {"provider": "nonexistent"})
        provider = get_provider(cfg)
        assert isinstance(provider, OpenAIProvider)
        captured = capsys.readouterr()
        assert "Unknown provider" in captured.out

    def test_none_config_gives_openai(self):
        provider = get_provider(None)
        assert isinstance(provider, OpenAIProvider)

    def test_embabel_without_mcp_package(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path, {"provider": "embabel"})
        with patch.dict("sys.modules", {"docgen.mcp_client": None}):
            provider = get_provider(cfg)
        assert isinstance(provider, OpenAIProvider)


# ---------------------------------------------------------------------------
# Config.ai_config
# ---------------------------------------------------------------------------


class TestAIConfig:
    def test_defaults(self, tmp_path):
        p = tmp_path / "docgen.yaml"
        p.write_text("{}", encoding="utf-8")
        cfg = Config.from_yaml(p)
        ai = cfg.ai_config
        assert ai["provider"] == "openai"
        assert ai["whisper_model"] == "whisper-1"
        assert ai["ollama_url"] == "http://localhost:11434"
        assert ai["embabel_url"] == "http://localhost:8080/sse"

    def test_custom_values(self, tmp_path):
        raw = {
            "ai": {
                "provider": "ollama",
                "whisper_model": "whisper-large-v3",
                "ollama_model": "mistral",
            }
        }
        p = tmp_path / "docgen.yaml"
        p.write_text(yaml.dump(raw), encoding="utf-8")
        cfg = Config.from_yaml(p)
        assert cfg.ai_config["provider"] == "ollama"
        assert cfg.ai_config["whisper_model"] == "whisper-large-v3"
        assert cfg.ai_config["ollama_model"] == "mistral"
