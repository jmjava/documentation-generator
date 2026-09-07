"""Tests for :mod:`docgen.ai_client` (OpenAI vs Grok resolution, no live network)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from docgen.ai_client import (
    DEFAULT_GROK_CHAT_MODEL,
    DEFAULT_GROK_IMAGE_MODEL,
    GROK_BASE_URL,
    chat_completion,
    openai_client,
    resolve_ai_settings,
    resolve_chat_model,
    resolve_image_model,
    resolve_tts_voice,
    synthesize_speech,
    transcribe_audio,
)
from docgen.config import Config


def _cfg(tmp_path: Path, raw: dict) -> Config:
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    return Config.from_yaml(p)


def test_default_provider_is_openai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCGEN_AI_PROVIDER", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = _cfg(tmp_path, {})
    st = resolve_ai_settings(cfg)
    assert st.provider == "openai"
    assert st.base_url is None
    assert st.api_key_env == "OPENAI_API_KEY"
    assert st.api_key is None


def test_yaml_provider_grok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCGEN_AI_PROVIDER", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    cfg = _cfg(tmp_path, {"ai": {"provider": "grok"}})
    st = resolve_ai_settings(cfg)
    assert st.provider == "grok"
    assert st.base_url == GROK_BASE_URL
    assert st.api_key == "xai-test"
    assert st.api_key_env == "XAI_API_KEY"


def test_env_overrides_yaml_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCGEN_AI_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    cfg = _cfg(tmp_path, {"ai": {"provider": "openai"}})
    assert resolve_ai_settings(cfg).provider == "grok"


def test_xai_alias_and_openai_model_remap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCGEN_AI_PROVIDER", "xai")
    cfg = _cfg(tmp_path, {})
    st = resolve_ai_settings(cfg)
    assert st.is_grok
    assert resolve_chat_model("gpt-4o", st) == DEFAULT_GROK_CHAT_MODEL
    assert resolve_chat_model("gpt-4o-mini", st) == DEFAULT_GROK_CHAT_MODEL
    assert resolve_chat_model("grok-4.6", st) == "grok-4.6"
    assert resolve_image_model("gpt-image-1", st) == DEFAULT_GROK_IMAGE_MODEL
    assert resolve_tts_voice("coral", st) == "eve"
    assert resolve_tts_voice("eve", st) == "eve"


def test_openai_client_grok_passes_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCGEN_AI_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    cfg = _cfg(tmp_path, {})
    captured: dict = {}

    def _fake_openai(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return MagicMock()

    with patch("openai.OpenAI", side_effect=_fake_openai):
        openai_client(cfg)
    assert captured["api_key"] == "xai-test"
    assert captured["base_url"] == GROK_BASE_URL


def test_openai_client_default_no_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCGEN_AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("openai.OpenAI") as m:
        m.return_value = MagicMock()
        openai_client(None)
    m.assert_called_once_with()


def test_chat_completion_uses_remapped_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCGEN_AI_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    cfg = _cfg(tmp_path, {})
    captured: dict = {}

    class _Msg:
        content = "ok"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    fake = MagicMock()
    fake.chat.completions.create.side_effect = lambda **kw: captured.update(kw) or _Resp()

    with patch("docgen.ai_client.openai_client", return_value=fake):
        out = chat_completion(
            system_prompt="sys",
            user_message="user",
            model="gpt-4o",
            temperature=0.2,
            cfg=cfg,
        )
    assert out == "ok"
    assert captured["model"] == DEFAULT_GROK_CHAT_MODEL


def test_grok_tts_posts_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCGEN_AI_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    cfg = _cfg(tmp_path, {"tts": {"voice": "coral", "language": "en"}})
    out = tmp_path / "n.mp3"

    def _http(url: str, *, data: bytes, headers: dict, **_kwargs) -> bytes:
        assert url.endswith("/tts")
        payload = json.loads(data.decode())
        assert payload["voice_id"] == "eve"
        assert payload["text"] == "Hello"
        assert "Bearer xai-test" in headers["Authorization"]
        return b"ID3fake"

    with patch("docgen.ai_client._http_with_retries", side_effect=_http):
        synthesize_speech(
            text="Hello",
            model="gpt-4o-mini-tts",
            voice="coral",
            instructions="unused on grok",
            output_path=out,
            cfg=cfg,
        )
    assert out.read_bytes() == b"ID3fake"


def test_grok_stt_maps_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCGEN_AI_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    cfg = _cfg(tmp_path, {})
    mp3 = tmp_path / "n.mp3"
    mp3.write_bytes(b"fake-mp3")
    body = json.dumps(
        {
            "text": "Hello world",
            "duration": 1.2,
            "words": [
                {"text": "Hello", "start": 0.0, "end": 0.4},
                {"text": "world", "start": 0.4, "end": 1.0},
            ],
        }
    ).encode()

    with patch("docgen.ai_client._http_with_retries", return_value=body):
        result = transcribe_audio(mp3, cfg=cfg)
    assert result["text"] == "Hello world"
    assert result["words"][0]["word"] == "Hello"
    assert result["words"][1]["end"] == 1.0
    assert result["segments"][0]["text"] == "Hello world"


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="Unknown AI provider"):
        from docgen.ai_client import normalize_provider

        normalize_provider("ollama")


def test_cursor_key_wins_over_openai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "sk-proj-cursor")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    st = resolve_ai_settings(_cfg(tmp_path, {}))
    assert st.provider == "openai"
    assert st.api_key == "sk-proj-cursor"
    assert st.api_key_env == "CURSOR_API_KEY"
    assert resolve_image_model("gpt-image-1", st) == "gpt-image-1"
    assert resolve_image_model("dall-e-3", st) == "dall-e-3"


def test_cursor_key_used_when_openai_is_crsr_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "sk-proj-cursor")
    monkeypatch.setenv("OPENAI_API_KEY", "crsr_cloud_proxy")
    st = resolve_ai_settings(_cfg(tmp_path, {}))
    assert st.api_key == "sk-proj-cursor"
    assert st.api_key_env == "CURSOR_API_KEY"


def test_openai_key_used_when_cursor_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    st = resolve_ai_settings(_cfg(tmp_path, {}))
    assert st.api_key == "sk-openai"
    assert st.api_key_env == "OPENAI_API_KEY"


def test_explicit_api_key_env_still_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "sk-proj-cursor")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    cfg = _cfg(tmp_path, {"ai": {"api_key_env": "OPENAI_API_KEY"}})
    st = resolve_ai_settings(cfg)
    assert st.api_key == "sk-openai"
    assert st.api_key_env == "OPENAI_API_KEY"


def test_anthropic_only_key_selects_claude_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOCGEN_AI_PROVIDER", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    st = resolve_ai_settings(_cfg(tmp_path, {}))
    assert st.provider == "anthropic"
    assert st.is_anthropic
    assert st.api_key == "sk-ant-test"
    assert st.supports_tts is False
    assert st.supports_images is False
    from docgen.ai_client import DEFAULT_ANTHROPIC_CHAT_MODEL

    assert resolve_chat_model("gpt-4o-mini", st) == DEFAULT_ANTHROPIC_CHAT_MODEL


def test_cursor_key_beats_anthropic_for_default_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOCGEN_AI_PROVIDER", raising=False)
    monkeypatch.setenv("CURSOR_API_KEY", "sk-proj-cursor")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    st = resolve_ai_settings(_cfg(tmp_path, {}))
    assert st.provider == "openai"
    assert st.api_key_env == "CURSOR_API_KEY"


def test_anthropic_chat_posts_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from docgen.ai_client import DEFAULT_ANTHROPIC_CHAT_MODEL

    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = _cfg(tmp_path, {})
    captured: dict = {}

    def _http(url: str, *, data: bytes, headers: dict, **_kwargs) -> bytes:
        captured["url"] = url
        captured["headers"] = headers
        payload = json.loads(data.decode())
        captured["payload"] = payload
        return json.dumps(
            {"content": [{"type": "text", "text": "spoken script"}]}
        ).encode()

    with patch("docgen.ai_client._http_with_retries", side_effect=_http):
        out = chat_completion(
            system_prompt="sys",
            user_message="user",
            model="gpt-4o-mini",
            temperature=0.2,
            cfg=cfg,
        )
    assert out == "spoken script"
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["payload"]["model"] == DEFAULT_ANTHROPIC_CHAT_MODEL


def test_anthropic_tts_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with pytest.raises(RuntimeError, match="no TTS"):
        synthesize_speech(
            text="Hello",
            model="gpt-4o-mini-tts",
            voice="coral",
            instructions="",
            output_path=tmp_path / "n.mp3",
            cfg=_cfg(tmp_path, {}),
        )
