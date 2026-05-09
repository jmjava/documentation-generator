"""Whisper-driven word-level alignment for narration audio.

The audio-driven sync pipeline:

1. ``synthesize_full_narration`` — concatenate every ``narration_steps[*].say``
   into ONE TTS pass. We ask the TTS once instead of stitching N independent
   clips so prosody, breath, and inter-sentence pacing sound natural.
2. ``whisper_align_steps`` — feed that single MP3 to OpenAI Whisper with
   ``timestamp_granularities=["word"]`` and walk the returned word stream,
   greedily matching each ``say`` to the next contiguous run of normalized
   tokens. Each step gets a ``(start_ms, end_ms)`` window in the audio.

The caller ( ``demo_function._align_visual_to_narration`` ) then asks a
vision LLM (see :mod:`docgen.pf_keyframes`) to pick one keyframe per step
from the source recording and assembles a slideshow MP4 holding each
chosen still for its Whisper-aligned duration. Audio is the master
clock: never time-stretched, never spliced, never re-mixed.

Whisper is the *only* timing source — there is no proportional / clip-length
fallback. If Whisper cannot align a step (network failure, missing tokens),
we raise so the caller fails loud rather than producing a desynced video.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WHISPER_MODEL = "whisper-1"


def _ToolingMissingError() -> type[Exception]:
    """Lazy-import the renderer's ``ToolingMissingError`` to dodge cycles.

    ``demo_function`` imports this module, so importing it back at
    module-import time would deadlock. Late-binding here keeps the
    dependency one-way for static analysis and at runtime.
    """
    from docgen.demo_function import ToolingMissingError as _T

    return _T


@dataclass(frozen=True)
class StepTiming:
    """Whisper-derived window for one ``narration_steps[i]`` entry."""

    start_ms: int
    end_ms: int
    matched_words: int
    total_words: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def synthesize_full_narration(
    steps: list[dict[str, Any]],
    out_path: Path,
    *,
    voice: str,
    model: str,
    tts_synthesize: Any,
) -> str:
    """Render ALL ``steps[*].say`` into one MP3 via ``tts_synthesize``.

    Returns the joined transcript string that was sent to TTS so the caller
    can pass it to Whisper as a ``prompt`` (improves recognition accuracy).

    ``tts_synthesize`` is injected (rather than imported) to keep this
    module decoupled from ``demo_function`` — facilitates unit-testing the
    alignment logic with a stub TTS.
    """
    if not steps:
        raise RuntimeError("synthesize_full_narration: no steps")
    text = _join_says(steps)
    tts_synthesize(text, out_path, voice=voice, model=model)
    return text


def whisper_align_steps(
    audio_path: Path,
    steps: list[dict[str, Any]],
    *,
    transcript_prompt: str | None = None,
    openai_client: Any | None = None,
) -> list[StepTiming]:
    """Run Whisper on ``audio_path`` and return per-step ``(start_ms, end_ms)``.

    Algorithm:

    * Request word-level timestamps from Whisper.
    * Normalize every word (lowercase, strip punctuation).
    * For each step, search forward from the current cursor for the FIRST
      occurrence of its first token, then walk in lock-step picking up
      consecutive token matches (skipping unrelated whisper words like
      hesitations or alternate spellings) until the step's tokens are
      exhausted or no more matches appear within a small look-ahead.
    * The step's ``start_ms`` is the start of its first matched word; its
      ``end_ms`` is the end of its last matched word.

    Raises ``RuntimeError`` if Whisper produced zero word-level timestamps,
    or if any step matched ZERO tokens (would silently mis-time the visual).
    """
    if not steps:
        return []
    words = _whisper_words(audio_path, prompt=transcript_prompt, client=openai_client)
    if not words:
        raise RuntimeError(
            "whisper produced no word-level timestamps for "
            f"{audio_path.name} — cannot align narration"
        )
    return _align_words_to_steps(words, steps)


def _join_says(steps: list[dict[str, Any]]) -> str:
    """Concatenate ``say`` strings into one paragraph TTS reads naturally.

    Each say is normalized to end in sentence-final punctuation so the TTS
    inserts a small breath between lines and Whisper's segmenter has clean
    sentence boundaries to anchor on.
    """
    parts: list[str] = []
    for entry in steps:
        say = str(entry.get("say", "")).strip()
        if not say:
            continue
        if not _ends_with_terminal_punct(say):
            say = say + "."
        parts.append(say)
    return " ".join(parts)


_TERMINAL_PUNCT = ".!?"


def _ends_with_terminal_punct(s: str) -> bool:
    return bool(s) and s[-1] in _TERMINAL_PUNCT


_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(token: str) -> str:
    """Lowercase + strip everything that isn't a-z / 0-9.

    Whisper sometimes emits tokens with attached punctuation (``"page."``)
    or different casing than our ``say`` text; normalization makes the two
    streams comparable without false negatives.
    """
    return _NORM_RE.sub("", token.lower())


def _word_text(w: Any) -> str:
    if isinstance(w, dict):
        return str(w.get("word", ""))
    return str(getattr(w, "word", ""))


def _word_start(w: Any) -> float:
    if isinstance(w, dict):
        return float(w.get("start", 0.0))
    return float(getattr(w, "start", 0.0))


def _word_end(w: Any) -> float:
    if isinstance(w, dict):
        return float(w.get("end", 0.0))
    return float(getattr(w, "end", 0.0))


def _align_words_to_steps(
    words: list[Any],
    steps: list[dict[str, Any]],
) -> list[StepTiming]:
    """Greedy in-order alignment of normalized whisper words to step tokens.

    Per-step look-ahead is bounded so a single misrecognized token can't
    consume the entire remaining word stream. We tolerate small skips
    (whisper might emit an extra interjection) but we never RE-match a
    word that's already been consumed by a previous step — order in the
    audio matches order in ``steps``.
    """
    timings: list[StepTiming] = []
    cursor = 0
    n_words = len(words)
    LOOKAHEAD = 8  # tolerate a handful of extra/missing tokens per step

    for step_idx, step in enumerate(steps):
        say = str(step.get("say", ""))
        tokens = [_norm(t) for t in say.split() if _norm(t)]
        total_tokens = len(tokens)
        if total_tokens == 0:
            raise RuntimeError(
                f"narration step {step_idx} has empty 'say' — cannot align"
            )

        first_token = tokens[0]
        start_idx: int | None = None
        for j in range(cursor, n_words):
            if _norm(_word_text(words[j])) == first_token:
                start_idx = j
                break
        if start_idx is None:
            raise RuntimeError(
                f"whisper alignment: step {step_idx} '{say!r}' first token "
                f"'{first_token}' not found from cursor={cursor} (whisper "
                f"transcribed {n_words} words; the audio likely doesn't "
                "contain this line — re-render the TTS or check the prompt)"
            )

        end_idx = start_idx
        matched = 1
        token_pos = 1
        scan = start_idx + 1
        while token_pos < total_tokens and scan < n_words:
            wnorm = _norm(_word_text(words[scan]))
            if wnorm == tokens[token_pos]:
                end_idx = scan
                matched += 1
                token_pos += 1
                scan += 1
                continue
            if scan - end_idx > LOOKAHEAD:
                break
            scan += 1

        if matched == 0:
            raise RuntimeError(
                f"whisper alignment: step {step_idx} matched 0 tokens"
            )

        start_ms = int(round(_word_start(words[start_idx]) * 1000))
        end_ms = int(round(_word_end(words[end_idx]) * 1000))
        if end_ms < start_ms:
            end_ms = start_ms
        timings.append(
            StepTiming(
                start_ms=start_ms,
                end_ms=end_ms,
                matched_words=matched,
                total_words=total_tokens,
            )
        )
        cursor = end_idx + 1

    _enforce_monotonic(timings)
    return timings


def _enforce_monotonic(timings: list[StepTiming]) -> None:
    """Sanity-check: each step must end at or after the previous step's end.

    Whisper word streams are intrinsically ordered, but our matcher could in
    principle pick a later token for step i and an earlier one for step
    i+1 if the recognition was very noisy. Catching that here protects
    downstream segment-stretch math from negative durations.
    """
    last_end = -1
    for i, t in enumerate(timings):
        if t.start_ms < last_end:
            raise RuntimeError(
                f"whisper alignment: step {i} starts before step {i - 1} "
                f"ends ({t.start_ms} < {last_end}); transcript is non-monotonic"
            )
        last_end = t.end_ms


def _whisper_words(
    audio_path: Path,
    *,
    prompt: str | None,
    client: Any | None,
) -> list[Any]:
    """Call OpenAI's Whisper transcription and return its word-list.

    Auth / connection errors are translated to ``ToolingMissingError`` /
    ``RuntimeError`` with actionable messages so the caller can surface a
    clear failure instead of a stack trace.
    """
    try:
        import openai
    except ImportError as exc:  # pragma: no cover - defensive
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            "openai package not available — needed for whisper alignment",
            install_hint="pip install openai",
        ) from exc

    if client is None:
        client = openai.OpenAI()

    kwargs: dict[str, Any] = {
        "model": WHISPER_MODEL,
        "response_format": "verbose_json",
        "timestamp_granularities": ["word"],
    }
    if prompt:
        kwargs["prompt"] = prompt[:1024]

    try:
        with open(audio_path, "rb") as fh:
            kwargs["file"] = fh
            resp = client.audio.transcriptions.create(**kwargs)
    except openai.AuthenticationError as exc:
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            f"OpenAI rejected OPENAI_API_KEY for whisper: {exc}",
            install_hint=(
                "Set a valid OPENAI_API_KEY whose project has whisper "
                "transcription access."
            ),
        ) from exc
    except openai.PermissionDeniedError as exc:
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            f"OPENAI_API_KEY lacks whisper-1 permissions: {exc}",
            install_hint=(
                "Use a key whose project has access to "
                "audio.transcriptions.create + the whisper-1 model."
            ),
        ) from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"OpenAI whisper network error: {exc} — re-run when connectivity "
            "is restored."
        ) from exc

    words = getattr(resp, "words", None)
    if words is None and isinstance(resp, dict):
        words = resp.get("words")
    return list(words or [])


__all__ = [
    "StepTiming",
    "WHISPER_MODEL",
    "synthesize_full_narration",
    "whisper_align_steps",
]
