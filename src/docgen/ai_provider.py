"""AI provider abstraction — decouples docgen from direct OpenAI API calls.

Supports multiple backends:
  - openai   (default) — direct OpenAI SDK calls
  - ollama   — local models via Ollama REST API (chat only; TTS/transcribe fall back)
  - embabel  — Embabel agent framework via MCP (future)

Usage:
    from docgen.ai_provider import get_provider
    provider = get_provider(config)
    text = provider.chat(messages=[...])
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from docgen.config import Config


class AIProviderError(RuntimeError):
    """Raised when an AI provider call fails."""


@runtime_checkable
class AIProvider(Protocol):
    """Protocol that all AI providers must satisfy."""

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """Generate a chat completion and return the assistant message text."""
        ...

    def tts(
        self,
        *,
        text: str,
        output_path: Path | str,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        **kwargs: Any,
    ) -> Path:
        """Generate speech audio and write it to *output_path*. Returns the path."""
        ...

    def transcribe(
        self,
        *,
        audio_path: Path | str,
        model: str | None = None,
        response_format: str = "verbose_json",
        timestamp_granularities: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Transcribe audio and return ``{text, segments, words}``."""
        ...


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


class OpenAIProvider:
    """Wraps the OpenAI Python SDK."""

    def __init__(
        self,
        *,
        default_chat_model: str = "gpt-4o",
        default_tts_model: str = "gpt-4o-mini-tts",
        default_tts_voice: str = "coral",
        default_whisper_model: str = "whisper-1",
    ) -> None:
        self.default_chat_model = default_chat_model
        self.default_tts_model = default_tts_model
        self.default_tts_voice = default_tts_voice
        self.default_whisper_model = default_whisper_model

    def _client(self):
        import openai

        return openai.OpenAI()

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        client = self._client()
        response = client.chat.completions.create(
            model=model or self.default_chat_model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def tts(
        self,
        *,
        text: str,
        output_path: Path | str,
        model: str | None = None,
        voice: str | None = None,
        instructions: str | None = None,
        **kwargs: Any,
    ) -> Path:
        client = self._client()
        create_kwargs: dict[str, Any] = {
            "model": model or self.default_tts_model,
            "voice": voice or self.default_tts_voice,
            "input": text,
        }
        if instructions:
            create_kwargs["instructions"] = instructions
        response = client.audio.speech.create(**create_kwargs)
        out = Path(output_path)
        response.stream_to_file(str(out))
        return out

    def transcribe(
        self,
        *,
        audio_path: Path | str,
        model: str | None = None,
        response_format: str = "verbose_json",
        timestamp_granularities: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        client = self._client()
        with open(audio_path, "rb") as f:
            create_kwargs: dict[str, Any] = {
                "model": model or self.default_whisper_model,
                "file": f,
                "response_format": response_format,
            }
            if timestamp_granularities:
                create_kwargs["timestamp_granularities"] = timestamp_granularities
            result = client.audio.transcriptions.create(**create_kwargs)

        return {
            "text": result.text,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in (result.segments or [])
            ],
            "words": [
                {"start": w.start, "end": w.end, "word": w.word}
                for w in (result.words or [])
            ],
        }


# ---------------------------------------------------------------------------
# Ollama provider (local models)
# ---------------------------------------------------------------------------


class OllamaProvider:
    """Local model support via Ollama REST API.

    Supports chat completions only.  TTS and transcription raise
    ``AIProviderError`` — callers should use a :class:`HybridProvider`
    that routes those to OpenAI.
    """

    def __init__(
        self,
        *,
        url: str = "http://localhost:11434",
        default_model: str = "llama3.2",
    ) -> None:
        self.url = url.rstrip("/")
        self.default_model = default_model

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        import json
        import urllib.request

        payload = json.dumps({
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            raise AIProviderError(f"Ollama request failed: {exc}") from exc

        return data.get("message", {}).get("content", "")

    def tts(self, **kwargs: Any) -> Path:
        raise AIProviderError(
            "Ollama does not support TTS. Configure a HybridProvider "
            "or set ai.tts_provider to 'openai'."
        )

    def transcribe(self, **kwargs: Any) -> dict[str, Any]:
        raise AIProviderError(
            "Ollama does not support transcription. Configure a HybridProvider "
            "or set ai.transcribe_provider to 'openai'."
        )


# ---------------------------------------------------------------------------
# Hybrid provider — routes capabilities to different backends
# ---------------------------------------------------------------------------


class HybridProvider:
    """Routes chat / tts / transcribe to different providers."""

    def __init__(
        self,
        *,
        chat_provider: AIProvider,
        tts_provider: AIProvider,
        transcribe_provider: AIProvider,
    ) -> None:
        self._chat = chat_provider
        self._tts = tts_provider
        self._transcribe = transcribe_provider

    def chat(self, **kwargs: Any) -> str:
        return self._chat.chat(**kwargs)

    def tts(self, **kwargs: Any) -> Path:
        return self._tts.tts(**kwargs)

    def transcribe(self, **kwargs: Any) -> dict[str, Any]:
        return self._transcribe.transcribe(**kwargs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_provider(config: Config | None = None) -> AIProvider:
    """Build an :class:`AIProvider` from a :class:`Config`.

    Resolution order:
      1. ``DOCGEN_AI_PROVIDER`` env var
      2. ``ai.provider`` in ``docgen.yaml``
      3. Default: ``openai``
    """
    if config is None:
        return OpenAIProvider()

    ai_cfg = config.ai_config
    provider_name = (
        os.environ.get("DOCGEN_AI_PROVIDER")
        or ai_cfg.get("provider", "openai")
    ).lower().strip()

    openai_defaults = {
        "default_chat_model": ai_cfg.get("chat_model", config.wizard_config.get("llm_model", "gpt-4o")),
        "default_tts_model": ai_cfg.get("tts_model", config.tts_model),
        "default_tts_voice": ai_cfg.get("tts_voice", config.tts_voice),
        "default_whisper_model": ai_cfg.get("whisper_model", "whisper-1"),
    }

    if provider_name == "openai":
        return OpenAIProvider(**openai_defaults)

    if provider_name == "ollama":
        ollama = OllamaProvider(
            url=ai_cfg.get("ollama_url", "http://localhost:11434"),
            default_model=ai_cfg.get("ollama_model", "llama3.2"),
        )
        openai_fallback = OpenAIProvider(**openai_defaults)
        return HybridProvider(
            chat_provider=ollama,
            tts_provider=openai_fallback,
            transcribe_provider=openai_fallback,
        )

    if provider_name == "embabel":
        embabel_url = ai_cfg.get("embabel_url", "http://localhost:8080/sse")
        try:
            from docgen.mcp_client import EmbabelSyncProvider

            return EmbabelSyncProvider(url=embabel_url)
        except ImportError:
            print(
                "[ai] Embabel provider requested but 'mcp' package not installed. "
                "Install with: pip install docgen[embabel]  — falling back to OpenAI."
            )
            return OpenAIProvider(**openai_defaults)
        except Exception as exc:
            print(f"[ai] Embabel connection failed ({exc}), falling back to OpenAI.")
            return OpenAIProvider(**openai_defaults)

    print(f"[ai] Unknown provider '{provider_name}', falling back to OpenAI.")
    return OpenAIProvider(**openai_defaults)
