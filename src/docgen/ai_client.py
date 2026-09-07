"""OpenAI-compatible AI client with first-class xAI / Grok support.

Chat completions and (most) image generation go through the official
``openai`` SDK. xAI speaks that protocol at ``https://api.x.ai/v1``, so
switching providers is ``base_url`` + key + model aliases.

TTS and speech-to-text are **not** drop-in compatible: OpenAI uses
``/v1/audio/speech`` and ``whisper-1``; xAI uses ``POST /v1/tts`` and
``POST /v1/stt``. Those paths are adapted here so ``docgen tts`` /
``timestamps --engine whisper`` keep working.

Resolution order for ``ai.provider``:

1. ``DOCGEN_AI_PROVIDER`` (``openai`` or ``grok`` / ``xai``)
2. ``ai.provider`` in ``docgen.yaml``
3. default ``openai`` (unchanged behaviour)

Grok auth reads ``XAI_API_KEY``, then ``OPENAI_API_KEY``. OpenAI auth
reads ``OPENAI_API_KEY`` only (unless ``ai.api_key_env`` overrides).
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config

GROK_BASE_URL = "https://api.x.ai/v1"
DEFAULT_GROK_CHAT_MODEL = "grok-4.6"
DEFAULT_GROK_IMAGE_MODEL = "grok-imagine-image-2.0"
DEFAULT_GROK_TTS_VOICE = "eve"
DEFAULT_GROK_TTS_LANGUAGE = "en"
GROK_TTS_MAX_CHARS = 15_000

_GROK_PROVIDERS = frozenset({"grok", "xai", "x.ai"})
_OPENAI_PROVIDERS = frozenset({"openai", "oai", ""})

# Existing yaml/init defaults keep OpenAI model names; remap at call time.
_GROK_CHAT_ALIASES = {
    "gpt-4o": DEFAULT_GROK_CHAT_MODEL,
    "gpt-4o-mini": DEFAULT_GROK_CHAT_MODEL,
    "gpt-4.1": DEFAULT_GROK_CHAT_MODEL,
    "gpt-4.1-mini": DEFAULT_GROK_CHAT_MODEL,
    "gpt-4.1-nano": DEFAULT_GROK_CHAT_MODEL,
    "gpt-4": DEFAULT_GROK_CHAT_MODEL,
    "gpt-3.5-turbo": DEFAULT_GROK_CHAT_MODEL,
}

_GROK_IMAGE_ALIASES = {
    "gpt-image-1": DEFAULT_GROK_IMAGE_MODEL,
    "gpt-image-1-mini": DEFAULT_GROK_IMAGE_MODEL,
    "dall-e-3": DEFAULT_GROK_IMAGE_MODEL,
    "dall-e-2": "grok-imagine-image",
}

_GROK_VOICES = frozenset({"eve", "ara", "rex", "sal", "leo"})
_OPENAI_TO_GROK_VOICE = {
    "alloy": "sal",
    "ash": "rex",
    "ballad": "leo",
    "coral": "eve",
    "echo": "rex",
    "fable": "leo",
    "nova": "ara",
    "onyx": "rex",
    "sage": "ara",
    "shimmer": "eve",
    "verse": "sal",
}

_API_KEY_ENVS = ("OPENAI_API_KEY", "XAI_API_KEY")
_MAX_HTTP_ATTEMPTS = 10
_BASE_DELAY_SEC = 1.0
_MAX_BACKOFF_SEC = 120.0


@dataclass(frozen=True)
class AISettings:
    provider: str  # "openai" | "grok"
    base_url: str | None
    api_key: str | None
    api_key_env: str
    tts_language: str

    @property
    def is_grok(self) -> bool:
        return self.provider == "grok"

    def auth_help(self) -> str:
        if self.is_grok:
            return (
                f"Set {self.api_key_env} (xAI / Grok), or OPENAI_API_KEY, "
                "and ai.provider: grok / DOCGEN_AI_PROVIDER=grok."
            )
        return (
            f"Set {self.api_key_env}, or switch to Grok with ai.provider: grok "
            "and XAI_API_KEY."
        )


def normalize_provider(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in _GROK_PROVIDERS:
        return "grok"
    if value in _OPENAI_PROVIDERS:
        return "openai"
    raise ValueError(
        f"Unknown AI provider {raw!r}; use 'openai' or 'grok' "
        "(aliases: xai, x.ai)."
    )


def resolve_ai_settings(cfg: "Config | None" = None) -> AISettings:
    """Resolve provider, base URL, and API key from env + optional bundle config."""
    block: dict[str, Any] = {}
    tts_language = DEFAULT_GROK_TTS_LANGUAGE
    if cfg is not None:
        raw_ai = cfg.raw.get("ai") if isinstance(cfg.raw, dict) else None
        if isinstance(raw_ai, dict):
            block = raw_ai
        tts = cfg.raw.get("tts") if isinstance(cfg.raw, dict) else None
        if isinstance(tts, dict):
            lang = str(tts.get("language") or "").strip()
            if lang:
                tts_language = lang

    env_provider = (os.environ.get("DOCGEN_AI_PROVIDER") or "").strip()
    yaml_provider = str(block.get("provider") or "").strip()
    provider = normalize_provider(env_provider or yaml_provider or "openai")

    env_base = (os.environ.get("DOCGEN_AI_BASE_URL") or "").strip()
    yaml_base = str(block.get("base_url") or "").strip()
    if env_base:
        base_url = env_base
    elif yaml_base:
        base_url = yaml_base
    elif provider == "grok":
        base_url = GROK_BASE_URL
    else:
        base_url = None

    env_key_name = (os.environ.get("DOCGEN_AI_API_KEY_ENV") or "").strip()
    yaml_key_name = str(block.get("api_key_env") or "").strip()
    if env_key_name:
        api_key_env = env_key_name
    elif yaml_key_name:
        api_key_env = yaml_key_name
    elif provider == "grok":
        api_key_env = "XAI_API_KEY"
    else:
        api_key_env = "OPENAI_API_KEY"

    api_key = (os.environ.get(api_key_env) or "").strip() or None
    if not api_key and provider == "grok":
        api_key = (os.environ.get("OPENAI_API_KEY") or "").strip() or None
        if api_key:
            api_key_env = "OPENAI_API_KEY"

    return AISettings(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        tts_language=tts_language,
    )


def openai_client(cfg: "Config | None" = None) -> Any:
    """Return an ``openai.OpenAI`` client, optionally pointed at xAI."""
    import openai

    settings = resolve_ai_settings(cfg)
    kwargs: dict[str, str] = {}
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return openai.OpenAI(**kwargs)


def resolve_chat_model(model: str, settings: AISettings | None = None, *, cfg: "Config | None" = None) -> str:
    chosen = (model or "").strip()
    st = settings or resolve_ai_settings(cfg)
    if not st.is_grok:
        return chosen
    if not chosen:
        return DEFAULT_GROK_CHAT_MODEL
    aliased = _GROK_CHAT_ALIASES.get(chosen)
    if aliased:
        return aliased
    if chosen.lower().startswith("gpt-"):
        return DEFAULT_GROK_CHAT_MODEL
    return chosen


def resolve_image_model(model: str, settings: AISettings | None = None, *, cfg: "Config | None" = None) -> str:
    chosen = (model or "").strip()
    st = settings or resolve_ai_settings(cfg)
    if not st.is_grok:
        return chosen
    if not chosen:
        return DEFAULT_GROK_IMAGE_MODEL
    aliased = _GROK_IMAGE_ALIASES.get(chosen)
    if aliased:
        return aliased
    if chosen.lower().startswith(("gpt-image", "dall-e")):
        return DEFAULT_GROK_IMAGE_MODEL
    return chosen


def resolve_tts_voice(voice: str, settings: AISettings | None = None, *, cfg: "Config | None" = None) -> str:
    chosen = (voice or "").strip()
    st = settings or resolve_ai_settings(cfg)
    if not st.is_grok:
        return chosen
    if chosen.lower() in _GROK_VOICES:
        return chosen.lower()
    return _OPENAI_TO_GROK_VOICE.get(chosen.lower(), DEFAULT_GROK_TTS_VOICE)


def chat_completion(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    cfg: "Config | None" = None,
) -> str:
    """Chat completions via the OpenAI SDK (OpenAI or xAI Grok)."""
    import openai

    settings = resolve_ai_settings(cfg)
    client = openai_client(cfg)
    resolved = resolve_chat_model(model, settings)
    try:
        response = client.chat.completions.create(
            model=resolved,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=float(temperature),
        )
    except openai.AuthenticationError as exc:
        raise RuntimeError(
            f"{_vendor(settings)} rejected {settings.api_key_env} (authentication failed): {exc}. "
            f"{settings.auth_help()}"
        ) from exc
    except openai.PermissionDeniedError as exc:
        raise RuntimeError(
            f"{_vendor(settings)} permission denied for model {resolved!r}: {exc}."
        ) from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"{_vendor(settings)} connection error: {exc} — re-run when connectivity is restored."
        ) from exc
    return response.choices[0].message.content or ""


def synthesize_speech(
    *,
    text: str,
    model: str,
    voice: str,
    instructions: str,
    output_path: Path,
    cfg: "Config | None" = None,
) -> None:
    """Write MP3 bytes for ``text`` using OpenAI TTS or xAI ``/v1/tts``."""
    settings = resolve_ai_settings(cfg)
    if settings.is_grok:
        _grok_tts(
            text=text,
            voice=resolve_tts_voice(voice, settings),
            language=settings.tts_language,
            output_path=output_path,
            settings=settings,
        )
        return

    client = openai_client(cfg)

    def _call() -> None:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            instructions=instructions,
        )
        response.stream_to_file(str(output_path))

    from docgen.openai_retry import call_with_rate_limit_retries

    call_with_rate_limit_retries(_call)


def transcribe_audio(audio_path: str | Path, *, cfg: "Config | None" = None) -> dict[str, Any]:
    """Return Whisper-shaped ``{text, segments, words}`` from OpenAI or xAI STT."""
    settings = resolve_ai_settings(cfg)
    if settings.is_grok:
        return _grok_stt(Path(audio_path), settings)

    client = openai_client(cfg)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
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


def fetch_url_bytes(url: str, *, timeout: int = 120) -> bytes:
    """GET ``url`` and return the response body (image CDN / signed URLs)."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _vendor(settings: AISettings) -> str:
    return "xAI" if settings.is_grok else "OpenAI"


def _grok_tts(
    *,
    text: str,
    voice: str,
    language: str,
    output_path: Path,
    settings: AISettings,
) -> None:
    if not settings.api_key:
        raise RuntimeError(f"xAI TTS needs an API key. {settings.auth_help()}")
    if len(text) > GROK_TTS_MAX_CHARS:
        raise RuntimeError(
            f"xAI TTS accepts at most {GROK_TTS_MAX_CHARS} characters "
            f"({len(text)} in this segment). Split the narration or shorten it."
        )
    payload = {
        "text": text,
        "voice_id": voice,
        "language": language or DEFAULT_GROK_TTS_LANGUAGE,
    }
    body = _http_json(
        f"{settings.base_url.rstrip('/')}/tts",
        payload,
        settings=settings,
        accept="audio/mpeg",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body)


def _grok_stt(audio_path: Path, settings: AISettings) -> dict[str, Any]:
    if not settings.api_key:
        raise RuntimeError(f"xAI STT needs an API key. {settings.auth_help()}")
    data = _http_multipart(
        f"{settings.base_url.rstrip('/')}/stt",
        fields={"language": settings.tts_language or DEFAULT_GROK_TTS_LANGUAGE},
        filename=audio_path.name,
        file_bytes=audio_path.read_bytes(),
        content_type="audio/mpeg",
        settings=settings,
    )
    parsed = json.loads(data.decode("utf-8"))
    text = str(parsed.get("text") or "")
    raw_words = parsed.get("words") or []
    words: list[dict[str, Any]] = []
    for w in raw_words:
        if not isinstance(w, dict):
            continue
        token = str(w.get("word") or w.get("text") or "").strip()
        if not token:
            continue
        words.append(
            {
                "start": float(w.get("start") or 0.0),
                "end": float(w.get("end") or 0.0),
                "word": token,
            }
        )
    duration = float(parsed.get("duration") or (words[-1]["end"] if words else 0.0))
    segments = parsed.get("segments")
    if not isinstance(segments, list) or not segments:
        segments = (
            [{"start": words[0]["start"], "end": words[-1]["end"], "text": text}]
            if words
            else [{"start": 0.0, "end": duration, "text": text}]
        )
    else:
        segments = [
            {
                "start": float(s.get("start") or 0.0),
                "end": float(s.get("end") or 0.0),
                "text": str(s.get("text") or ""),
            }
            for s in segments
            if isinstance(s, dict)
        ]
    return {"text": text, "segments": segments, "words": words}


def _http_json(
    url: str,
    payload: dict[str, Any],
    *,
    settings: AISettings,
    accept: str = "application/json",
) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "Accept": accept,
    }
    return _http_with_retries(url, data=data, headers=headers)


def _http_multipart(
    url: str,
    *,
    fields: dict[str, str],
    filename: str,
    file_bytes: bytes,
    content_type: str,
    settings: AISettings,
) -> bytes:
    boundary = "----docgen" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8") + b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    chunks.append(file_bytes)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    }
    return _http_with_retries(url, data=body, headers=headers)


def _http_with_retries(url: str, *, data: bytes, headers: dict[str, str]) -> bytes:
    last_exc: BaseException | None = None
    for attempt in range(_MAX_HTTP_ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < _MAX_HTTP_ATTEMPTS - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = _retry_delay_sec(retry_after, attempt)
                time.sleep(delay)
                continue
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise RuntimeError(
                f"xAI HTTP {exc.code} for {url}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"xAI connection error for {url}: {exc}") from exc
    raise RuntimeError(f"xAI request failed after retries: {last_exc}")


def _retry_delay_sec(retry_after: str | None, attempt: int) -> float:
    delay: float | None = None
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            delay = None
    if delay is None or delay <= 0:
        delay = min(_MAX_BACKOFF_SEC, _BASE_DELAY_SEC * (2**attempt))
    jitter = random.uniform(0, max(0.05, 0.15 * delay))
    return delay + jitter


def conflicting_api_key_envs() -> tuple[str, ...]:
    """Env names that warn when both the shell and ``env_file`` set them."""
    return _API_KEY_ENVS
