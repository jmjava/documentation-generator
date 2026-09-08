"""AI client used by narration, scene-spec, TTS, STT, and images.

The CLI is **not** tied to Cursor. The same commands run in:

* Cursor Cloud automation (``CURSOR_API_KEY`` is injected)
* local Cursor (``.env`` ``OPENAI_API_KEY``, or ``CURSOR_API_KEY``)
* Claude Code / Copilot / plain shell (``.env`` ``OPENAI_API_KEY``, or
  ``ANTHROPIC_API_KEY`` for chat, or ``XAI_API_KEY`` for Grok)

Chat + images for OpenAI/Grok go through the ``openai`` SDK. xAI is
``base_url=https://api.x.ai/v1`` plus model aliases. Anthropic chat uses
``POST https://api.anthropic.com/v1/messages`` (no TTS/images there).

TTS/STT: OpenAI ``/v1/audio/speech`` + ``whisper-1``, or xAI ``/v1/tts``
and ``/v1/stt``.

Provider resolution:

1. ``DOCGEN_AI_PROVIDER``
2. ``ai.provider`` in ``docgen.yaml``
3. If a usable Cursor/OpenAI key exists → ``openai``
4. Else if ``ANTHROPIC_API_KEY`` is set → ``anthropic``
5. Else ``openai`` (error text then lists every key)

OpenAI-provider keys: ``CURSOR_API_KEY`` first, then ``OPENAI_API_KEY``.
Cursor Cloud's ``crsr_`` ``OPENAI_API_KEY`` proxy is skipped.
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
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

if TYPE_CHECKING:
    from docgen.config import Config

ProviderName: TypeAlias = Literal["openai", "grok", "anthropic"]


class AIError(RuntimeError):
    """Auth, HTTP, or capability failure from an AI provider call."""


GROK_BASE_URL = "https://api.x.ai/v1"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_GROK_CHAT_MODEL = "grok-4.6"
DEFAULT_GROK_IMAGE_MODEL = "grok-imagine-image-2.0"
DEFAULT_GROK_TTS_VOICE = "eve"
DEFAULT_GROK_TTS_LANGUAGE = "en"
DEFAULT_ANTHROPIC_CHAT_MODEL = "claude-sonnet-4-5"
GROK_TTS_MAX_CHARS = 15_000

_GROK_PROVIDERS = frozenset({"grok", "xai", "x.ai"})
_ANTHROPIC_PROVIDERS = frozenset({"anthropic", "claude", "claude-code"})
_OPENAI_PROVIDERS = frozenset({"openai", "oai", ""})

# Existing yaml/init defaults keep OpenAI model names; remap at call time.
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

_API_KEY_ENVS = ("CURSOR_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY")
_CURSOR_CLOUD_PROXY_PREFIX = "crsr_"
_MAX_HTTP_ATTEMPTS = 10
_BASE_DELAY_SEC = 1.0
_MAX_BACKOFF_SEC = 120.0
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
ANTHROPIC_MAX_TOKENS = 8192


@dataclass(frozen=True)
class AISettings:
    provider: ProviderName
    base_url: str | None
    api_key: str | None
    api_key_env: str
    tts_language: str

    @property
    def is_grok(self) -> bool:
        return self.provider == "grok"

    @property
    def is_anthropic(self) -> bool:
        return self.provider == "anthropic"

    @property
    def supports_tts(self) -> bool:
        return self.provider in {"openai", "grok"}

    @property
    def supports_images(self) -> bool:
        return self.provider in {"openai", "grok"}

    @property
    def supports_stt(self) -> bool:
        return self.provider in {"openai", "grok"}

    def auth_help(self) -> str:
        return (
            "docgen is not tied to one IDE. Set a key for your host: "
            "CURSOR_API_KEY (Cursor Cloud automation, injected), "
            "OPENAI_API_KEY (local Cursor, Claude Code, Copilot, CI .env), "
            "ANTHROPIC_API_KEY (Claude chat; ai.provider: anthropic, or auto "
            "when no OpenAI/Cursor key is present — TTS/images still need "
            "OpenAI or Grok), "
            "XAI_API_KEY (Grok; ai.provider: grok)."
        )


def normalize_provider(raw: str | None) -> ProviderName:
    value = (raw or "").strip().lower()
    if value in _GROK_PROVIDERS:
        return "grok"
    if value in _ANTHROPIC_PROVIDERS:
        return "anthropic"
    if value in _OPENAI_PROVIDERS:
        return "openai"
    raise ValueError(
        f"Unknown AI provider {raw!r}; use 'openai', 'grok', or 'anthropic' "
        "(aliases: xai, x.ai, claude, claude-code)."
    )


def _env_secret(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    return value or None


def _usable_secret(name: str) -> str | None:
    """Return a key that the target HTTP API can actually accept.

    Cursor Cloud injects ``OPENAI_API_KEY=crsr_…``; OpenAI's API 401s that
    token. Skip ``crsr_`` values so ``CURSOR_API_KEY`` / ``.env`` can win.
    """
    value = _env_secret(name)
    if not value:
        return None
    if value.lower().startswith(_CURSOR_CLOUD_PROXY_PREFIX):
        return None
    return value


def _pick_api_key(provider: ProviderName, *, explicit_env: str) -> tuple[str | None, str]:
    """Return ``(api_key, env_name)`` for the resolved provider."""
    if explicit_env:
        key = _usable_secret(explicit_env)
        if key:
            return key, explicit_env
        if not _env_secret(explicit_env):
            return None, explicit_env
        # Present but unusable (crsr_ proxy): fall through to the provider chain.

    if provider == "grok":
        for name in ("XAI_API_KEY", "OPENAI_API_KEY"):
            key = _usable_secret(name)
            if key:
                return key, name
        return None, "XAI_API_KEY"

    if provider == "anthropic":
        key = _usable_secret("ANTHROPIC_API_KEY")
        return key, "ANTHROPIC_API_KEY"

    for name in ("CURSOR_API_KEY", "OPENAI_API_KEY"):
        key = _usable_secret(name)
        if key:
            return key, name
    return None, "OPENAI_API_KEY"


def _implicit_provider() -> ProviderName:
    """When yaml/env omit provider: OpenAI, else Grok, else Anthropic.

    ``docgen init`` writes ``ai.provider: openai`` as a default. Treat that as
    implicit so a Grok-only ``XAI_API_KEY`` or Claude-only ``ANTHROPIC_API_KEY``
    still selects the matching host. Prefer Grok over Anthropic when both are
    present — Grok has TTS/images.
    """
    if _usable_secret("CURSOR_API_KEY") or _usable_secret("OPENAI_API_KEY"):
        return "openai"
    if _usable_secret("XAI_API_KEY"):
        return "grok"
    if _usable_secret("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "openai"


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
    if env_provider:
        provider = normalize_provider(env_provider)
    elif yaml_provider:
        named = normalize_provider(yaml_provider)
        # ``docgen init`` always writes ``ai.provider: openai``. Treat that as a
        # default so Claude Code users with only ANTHROPIC_API_KEY still get chat.
        provider = _implicit_provider() if named == "openai" else named
    else:
        provider = _implicit_provider()

    env_base = (os.environ.get("DOCGEN_AI_BASE_URL") or "").strip()
    yaml_base = str(block.get("base_url") or "").strip()
    if env_base:
        base_url = env_base
    elif yaml_base:
        base_url = yaml_base
    elif provider == "grok":
        base_url = GROK_BASE_URL
    elif provider == "anthropic":
        base_url = "https://api.anthropic.com"
    else:
        base_url = None

    env_key_name = (os.environ.get("DOCGEN_AI_API_KEY_ENV") or "").strip()
    yaml_key_name = str(block.get("api_key_env") or "").strip()
    explicit_env = env_key_name or yaml_key_name
    api_key, api_key_env = _pick_api_key(provider, explicit_env=explicit_env)

    return AISettings(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        api_key_env=api_key_env,
        tts_language=tts_language,
    )


def require_api_key(settings: AISettings) -> str:
    """Return the resolved secret, or raise before the SDK can pick a ``crsr_`` env fallback."""
    if settings.api_key:
        return settings.api_key
    raise AIError(
        f"No usable API key for provider {settings.provider!r} "
        f"(looked at {settings.api_key_env}). {settings.auth_help()}"
    )


def openai_client(cfg: "Config | None" = None) -> Any:
    """Return an ``openai.OpenAI`` client, optionally pointed at xAI."""
    import openai

    settings = resolve_ai_settings(cfg)
    if settings.is_anthropic:
        raise AIError(
            "The OpenAI SDK is not used for Anthropic. Call chat_completion() "
            f"for Claude chat. {settings.auth_help()}"
        )
    kwargs: dict[str, str] = {"api_key": require_api_key(settings)}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return openai.OpenAI(**kwargs)


def resolve_chat_model(model: str, settings: AISettings | None = None, *, cfg: "Config | None" = None) -> str:
    chosen = (model or "").strip()
    st = settings or resolve_ai_settings(cfg)
    if st.provider == "openai":
        return chosen
    default = DEFAULT_GROK_CHAT_MODEL if st.is_grok else DEFAULT_ANTHROPIC_CHAT_MODEL
    if not chosen or chosen.lower().startswith("gpt-"):
        return default
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
    """Chat completions via OpenAI, xAI Grok, or Anthropic Claude."""
    settings = resolve_ai_settings(cfg)
    resolved = resolve_chat_model(model, settings)
    if settings.is_anthropic:
        return _anthropic_chat(
            system_prompt=system_prompt,
            user_message=user_message,
            model=resolved,
            temperature=temperature,
            settings=settings,
        )

    import openai

    from docgen.openai_retry import call_with_rate_limit_retries

    client = openai_client(cfg)

    def _create() -> Any:
        return client.chat.completions.create(
            model=resolved,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=float(temperature),
        )

    try:
        response = call_with_rate_limit_retries(_create)
    except openai.AuthenticationError as exc:
        raise AIError(
            f"{_vendor(settings)} rejected {settings.api_key_env} (authentication failed): {exc}. "
            f"{settings.auth_help()}"
        ) from exc
    except openai.PermissionDeniedError as exc:
        raise AIError(
            f"{_vendor(settings)} permission denied for model {resolved!r}: {exc}."
        ) from exc
    except openai.RateLimitError as exc:
        raise AIError(
            f"{_vendor(settings)} rate-limited for model {resolved!r}: {exc}."
        ) from exc
    except openai.APIConnectionError as exc:
        raise AIError(
            f"{_vendor(settings)} connection error: {exc} — re-run when connectivity is restored."
        ) from exc
    try:
        text = (response.choices[0].message.content or "").strip()
    except (IndexError, AttributeError):
        text = ""
    if not text:
        raise AIError(f"{_vendor(settings)} chat returned no text content.")
    return text


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
    if settings.is_anthropic:
        raise AIError(
            "Anthropic has no TTS API. Use OPENAI_API_KEY / CURSOR_API_KEY "
            "(ai.provider: openai) or XAI_API_KEY (ai.provider: grok) for "
            f"`docgen tts`. {settings.auth_help()}"
        )
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
    if settings.is_anthropic:
        raise AIError(
            "Anthropic has no speech-to-text API. Keep timestamps.engine: local "
            f"(offline) or use OpenAI/Grok for whisper. {settings.auth_help()}"
        )
    if settings.is_grok:
        return _grok_stt(Path(audio_path), settings)

    import openai

    from docgen.openai_retry import call_with_rate_limit_retries

    client = openai_client(cfg)

    def _call() -> Any:
        with open(audio_path, "rb") as f:
            return client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )

    try:
        result = call_with_rate_limit_retries(_call)
    except openai.RateLimitError as exc:
        raise AIError(f"{_vendor(settings)} rate-limited whisper STT: {exc}.") from exc
    except openai.APIConnectionError as exc:
        raise AIError(
            f"{_vendor(settings)} connection error: {exc} — re-run when connectivity is restored."
        ) from exc
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
    last_exc: BaseException | None = None
    for attempt in range(_MAX_HTTP_ATTEMPTS):
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_HTTP_CODES and attempt < _MAX_HTTP_ATTEMPTS - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    if exc.fp is not None:
                        exc.fp.close()
                except OSError:
                    pass
                time.sleep(_retry_delay_sec(retry_after, attempt))
                continue
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise AIError(
                f"GET HTTP {exc.code} for {url}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < _MAX_HTTP_ATTEMPTS - 1:
                time.sleep(_retry_delay_sec(None, attempt))
                continue
            raise AIError(f"GET connection error for {url}: {exc}") from exc
    raise AIError(f"GET request failed after retries: {last_exc}")


def _vendor(settings: AISettings) -> str:
    if settings.is_grok:
        return "xAI"
    if settings.is_anthropic:
        return "Anthropic"
    return "OpenAI"


def detect_host() -> str:
    if (os.environ.get("CURSOR_AGENT") or "").strip() == "1":
        return "cursor-cloud"
    if (os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE") or "").strip():
        return "claude-code"
    return "generic"


def format_ai_status_line(settings: AISettings | None = None, *, cfg: "Config | None" = None) -> str:
    st = settings or resolve_ai_settings(cfg)
    present = "present" if st.api_key else "missing"
    host = detect_host()
    return (
        f"[docgen] AI provider={st.provider} {st.api_key_env}={present} "
        f"chat=yes tts={'yes' if st.supports_tts else 'no'} "
        f"images={'yes' if st.supports_images else 'no'} host={host}"
    )


def echo_ai_status(cfg: "Config | None" = None) -> None:
    """Print resolved provider/key (no secret) to stderr."""
    import click

    click.echo(format_ai_status_line(cfg=cfg), err=True)


def _anthropic_messages_url(settings: AISettings) -> str:
    """Chat completions URL for Anthropic or a compatible proxy."""
    base = (settings.base_url or "https://api.anthropic.com").rstrip("/")
    if base == "https://api.anthropic.com":
        return ANTHROPIC_MESSAGES_URL
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _anthropic_chat(
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    settings: AISettings,
) -> str:
    if not settings.api_key:
        raise AIError(f"Anthropic chat needs ANTHROPIC_API_KEY. {settings.auth_help()}")
    payload = {
        "model": model,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "temperature": float(temperature),
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    raw = _http_json(
        _anthropic_messages_url(settings),
        payload,
        settings=settings,
        accept="application/json",
        extra_headers={
            "x-api-key": settings.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        error_label="Anthropic",
        skip_bearer=True,
    )
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AIError(f"Anthropic chat returned non-JSON: {raw[:200]!r}") from exc
    blocks = data.get("content") or []
    texts = [b.get("text") or "" for b in blocks if isinstance(b, dict)]
    text = "".join(texts).strip()
    if not text:
        raise AIError("Anthropic chat returned no text content.")
    return text


def _grok_tts(
    *,
    text: str,
    voice: str,
    language: str,
    output_path: Path,
    settings: AISettings,
) -> None:
    if not settings.api_key:
        raise AIError(f"xAI TTS needs an API key. {settings.auth_help()}")
    if len(text) > GROK_TTS_MAX_CHARS:
        raise AIError(
            f"xAI TTS accepts at most {GROK_TTS_MAX_CHARS} characters "
            f"({len(text)} in this segment). Split the narration or shorten it."
        )
    payload = {
        "text": text,
        "voice_id": voice,
        "language": language or DEFAULT_GROK_TTS_LANGUAGE,
    }
    body = _http_json(
        f"{(settings.base_url or GROK_BASE_URL).rstrip('/')}/tts",
        payload,
        settings=settings,
        accept="audio/mpeg",
        error_label="xAI",
    )
    if not body:
        raise AIError("xAI TTS returned empty audio")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(body)


def _stt_json_number(value: Any, *, label: str) -> float:
    """Require a JSON number so bools/strings do not become fake timestamps."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AIError(
            f"xAI STT {label} must be a JSON number, not {type(value).__name__} "
            f"({value!r})"
        )
    return float(value)


def _grok_stt(audio_path: Path, settings: AISettings) -> dict[str, Any]:
    if not settings.api_key:
        raise AIError(f"xAI STT needs an API key. {settings.auth_help()}")
    data = _http_multipart(
        f"{(settings.base_url or GROK_BASE_URL).rstrip('/')}/stt",
        fields={"language": settings.tts_language or DEFAULT_GROK_TTS_LANGUAGE},
        filename=audio_path.name,
        file_bytes=audio_path.read_bytes(),
        content_type="audio/mpeg",
        settings=settings,
    )
    try:
        parsed = json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AIError(f"xAI STT returned non-JSON: {data[:200]!r}") from exc
    text = str(parsed.get("text") or "")
    raw_words = parsed.get("words")
    if raw_words is None:
        raw_words = []
    elif not isinstance(raw_words, list):
        raise AIError(
            f"xAI STT words must be a JSON array, not {type(raw_words).__name__}"
        )
    words: list[dict[str, Any]] = []
    for i, w in enumerate(raw_words):
        if not isinstance(w, dict):
            raise AIError(
                f"xAI STT words[{i}] must be a JSON object, not {type(w).__name__}"
            )
        token = str(w.get("word") or w.get("text") or "").strip()
        if not token:
            continue
        words.append(
            {
                "start": _stt_json_number(w.get("start"), label="words[].start"),
                "end": _stt_json_number(w.get("end"), label="words[].end"),
                "word": token,
            }
        )
    raw_dur = parsed.get("duration")
    if raw_dur is None:
        duration = words[-1]["end"] if words else 0.0
    else:
        duration = _stt_json_number(raw_dur, label="duration")
    segments = parsed.get("segments")
    if segments is None:
        segments = []
    elif not isinstance(segments, list):
        raise AIError(
            f"xAI STT segments must be a JSON array, not {type(segments).__name__}"
        )
    if not segments:
        segments = (
            [{"start": words[0]["start"], "end": words[-1]["end"], "text": text}]
            if words
            else [{"start": 0.0, "end": duration, "text": text}]
        )
    else:
        typed_segments: list[dict[str, Any]] = []
        for i, s in enumerate(segments):
            if not isinstance(s, dict):
                raise AIError(
                    f"xAI STT segments[{i}] must be a JSON object, not {type(s).__name__}"
                )
            typed_segments.append(
                {
                    "start": _stt_json_number(s.get("start"), label="segments[].start"),
                    "end": _stt_json_number(s.get("end"), label="segments[].end"),
                    "text": str(s.get("text") or ""),
                }
            )
        segments = typed_segments
    return {"text": text, "segments": segments, "words": words}


def _http_json(
    url: str,
    payload: dict[str, Any],
    *,
    settings: AISettings,
    accept: str = "application/json",
    extra_headers: dict[str, str] | None = None,
    skip_bearer: bool = False,
    error_label: str = "API",
) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    if not skip_bearer:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    if extra_headers:
        headers.update(extra_headers)
    return _http_with_retries(url, data=data, headers=headers, error_label=error_label)


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
    return _http_with_retries(url, data=body, headers=headers, error_label="xAI")


def _http_with_retries(
    url: str, *, data: bytes, headers: dict[str, str], error_label: str = "API"
) -> bytes:
    last_exc: BaseException | None = None
    for attempt in range(_MAX_HTTP_ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_HTTP_CODES and attempt < _MAX_HTTP_ATTEMPTS - 1:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = _retry_delay_sec(retry_after, attempt)
                try:
                    if exc.fp is not None:
                        exc.fp.close()
                except OSError:
                    pass
                time.sleep(delay)
                continue
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise AIError(
                f"{error_label} HTTP {exc.code} for {url}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < _MAX_HTTP_ATTEMPTS - 1:
                time.sleep(_retry_delay_sec(None, attempt))
                continue
            raise AIError(f"{error_label} connection error for {url}: {exc}") from exc
    raise AIError(f"{error_label} request failed after retries: {last_exc}")


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
