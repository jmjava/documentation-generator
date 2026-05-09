"""Unit tests for :mod:`docgen.pf_align` — Whisper-driven word alignment.

These tests cover the alignment logic in isolation without hitting the
network: every test injects a fake Whisper word stream so behavior is
deterministic. The OpenAI client wrapper itself is exercised via the
shared ``_whisper_words`` indirection in ``test_pf_align_client_failures``
which patches the ``openai`` module.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from docgen import pf_align


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _word(text: str, start: float, end: float) -> dict[str, Any]:
    """Build a Whisper-shaped word dict — ``{"word": ..., "start": ..., "end": ...}``."""
    return {"word": text, "start": float(start), "end": float(end)}


def _steps(*lines: str) -> list[dict[str, Any]]:
    return [{"say": line, "api_name": "page.goto"} for line in lines]


# ---------------------------------------------------------------------------
# _join_says
# ---------------------------------------------------------------------------


def test_join_says_adds_terminal_punct_when_missing() -> None:
    out = pf_align._join_says(_steps("Open the home page", "Click the button."))
    assert out == "Open the home page. Click the button."


def test_join_says_skips_blank_entries() -> None:
    out = pf_align._join_says(
        [{"say": "First."}, {"say": "   "}, {"say": "Third."}]
    )
    assert out == "First. Third."


# ---------------------------------------------------------------------------
# _norm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Page.", "page"),
        ("Don't!", "dont"),
        ("home,", "home"),
        ("123-abc", "123abc"),
        ("", ""),
        ("...", ""),
    ],
)
def test_norm_strips_case_and_punct(raw: str, expected: str) -> None:
    assert pf_align._norm(raw) == expected


# ---------------------------------------------------------------------------
# _align_words_to_steps — the meat
# ---------------------------------------------------------------------------


def test_align_simple_two_steps_produces_per_step_windows() -> None:
    """Each step's window spans its first → last matched word."""
    words = [
        _word("Open", 0.20, 0.40),
        _word("the", 0.41, 0.50),
        _word("home", 0.51, 0.70),
        _word("page.", 0.71, 1.00),
        _word("Click", 1.40, 1.60),
        _word("the", 1.61, 1.70),
        _word("button.", 1.71, 2.00),
    ]
    timings = pf_align._align_words_to_steps(
        words, _steps("Open the home page.", "Click the button.")
    )
    assert len(timings) == 2
    assert timings[0].start_ms == 200
    assert timings[0].end_ms == 1000
    assert timings[0].matched_words == 4
    assert timings[1].start_ms == 1400
    assert timings[1].end_ms == 2000
    assert timings[1].matched_words == 3


def test_align_tolerates_extra_whisper_words_within_lookahead() -> None:
    """A spurious recognized word between matches must NOT abort alignment."""
    words = [
        _word("Open", 0.0, 0.2),
        _word("uhh", 0.21, 0.30),
        _word("the", 0.31, 0.40),
        _word("home", 0.41, 0.55),
        _word("page", 0.56, 0.80),
    ]
    timings = pf_align._align_words_to_steps(
        words, _steps("Open the home page.")
    )
    assert timings[0].start_ms == 0
    assert timings[0].end_ms == 800
    assert timings[0].matched_words == 4


def test_align_consumes_words_in_order_no_rematch() -> None:
    """Once step 0 consumes a word, step 1 cannot match the same word."""
    # Two identical sentences in the audio — alignment must walk forward.
    words = [
        _word("Hello", 0.0, 0.5),
        _word("there", 0.6, 1.0),
        _word("Hello", 2.0, 2.5),
        _word("there", 2.6, 3.0),
    ]
    timings = pf_align._align_words_to_steps(
        words, _steps("Hello there.", "Hello there.")
    )
    assert timings[0].start_ms == 0
    assert timings[0].end_ms == 1000
    assert timings[1].start_ms == 2000
    assert timings[1].end_ms == 3000


def test_align_raises_when_step_first_token_absent() -> None:
    """If Whisper completely missed a step's first word, fail loudly."""
    words = [_word("Open", 0.0, 0.5)]
    with pytest.raises(RuntimeError, match="first token .* not found"):
        pf_align._align_words_to_steps(
            words, _steps("Open page.", "Click button.")
        )


def test_align_raises_when_empty_say() -> None:
    with pytest.raises(RuntimeError, match="empty 'say'"):
        pf_align._align_words_to_steps(
            [_word("hi", 0, 0.1)], [{"say": "  ", "api_name": "x"}]
        )


def test_align_enforces_monotonic_step_order() -> None:
    """Hand-crafted (defensive) check: out-of-order timings must error."""
    # The matcher's own greedy walk is monotonic, so we exercise the helper
    # directly with manually constructed timings.
    bad = [
        pf_align.StepTiming(start_ms=1000, end_ms=2000, matched_words=2, total_words=2),
        pf_align.StepTiming(start_ms=500, end_ms=1500, matched_words=2, total_words=2),
    ]
    with pytest.raises(RuntimeError, match="non-monotonic"):
        pf_align._enforce_monotonic(bad)


def test_align_handles_punctuation_and_case_in_whisper_words() -> None:
    """Whisper sometimes emits ``"page."`` with attached punctuation."""
    words = [
        _word("OPEN,", 0.0, 0.3),
        _word("THE", 0.31, 0.40),
        _word("home.", 0.41, 0.70),
    ]
    timings = pf_align._align_words_to_steps(
        words, _steps("Open the home.")
    )
    assert timings[0].matched_words == 3
    assert timings[0].start_ms == 0
    assert timings[0].end_ms == 700


# ---------------------------------------------------------------------------
# whisper_align_steps — uses the OpenAI client (faked via a stub)
# ---------------------------------------------------------------------------


class _FakeWhisperResp:
    def __init__(self, words: list[dict[str, Any]]) -> None:
        self.words = words


class _FakeOpenAIClient:
    """Minimal stand-in for ``openai.OpenAI()``.

    Records the kwargs we received so tests can assert that
    ``whisper_align_steps`` requested the right model + timestamp granularity.
    """

    def __init__(self, response_words: list[dict[str, Any]]) -> None:
        self._words = response_words
        self.last_kwargs: dict[str, Any] | None = None

        class _Audio:
            class _Transcriptions:
                def __init__(_self) -> None:
                    pass

                def create(_self, **kwargs: Any) -> _FakeWhisperResp:
                    self.last_kwargs = kwargs
                    return _FakeWhisperResp(self._words)

            def __init__(_self) -> None:
                _self.transcriptions = _Audio._Transcriptions()

        self.audio = _Audio()


def _write_dummy_audio(path: Path) -> None:
    path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")  # arbitrary mp3 header


def test_whisper_align_steps_passes_word_granularity_and_prompt(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "audio.mp3"
    _write_dummy_audio(audio)
    fake_words = [
        _word("Hi", 0.0, 0.4),
        _word("there.", 0.5, 1.0),
    ]
    client = _FakeOpenAIClient(fake_words)
    timings = pf_align.whisper_align_steps(
        audio,
        _steps("Hi there."),
        transcript_prompt="Hi there.",
        openai_client=client,
    )
    assert client.last_kwargs is not None
    assert client.last_kwargs["model"] == pf_align.WHISPER_MODEL
    assert client.last_kwargs["response_format"] == "verbose_json"
    assert client.last_kwargs["timestamp_granularities"] == ["word"]
    assert client.last_kwargs["prompt"] == "Hi there."
    assert len(timings) == 1
    assert timings[0].start_ms == 0
    assert timings[0].end_ms == 1000


def test_whisper_align_steps_truncates_overlong_prompt(tmp_path: Path) -> None:
    audio = tmp_path / "a.mp3"
    _write_dummy_audio(audio)
    long_prompt = "x" * 3000
    client = _FakeOpenAIClient([_word("hi", 0, 0.1)])
    pf_align.whisper_align_steps(
        audio,
        _steps("hi."),
        transcript_prompt=long_prompt,
        openai_client=client,
    )
    assert client.last_kwargs is not None
    assert len(client.last_kwargs["prompt"]) == 1024


def test_whisper_align_steps_returns_empty_for_no_steps(tmp_path: Path) -> None:
    audio = tmp_path / "a.mp3"
    _write_dummy_audio(audio)
    client = _FakeOpenAIClient([])
    assert pf_align.whisper_align_steps(audio, [], openai_client=client) == []


def test_whisper_align_steps_raises_when_no_words_returned(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "a.mp3"
    _write_dummy_audio(audio)
    client = _FakeOpenAIClient([])
    with pytest.raises(RuntimeError, match="no word-level timestamps"):
        pf_align.whisper_align_steps(
            audio, _steps("hi."), openai_client=client
        )


def test_whisper_align_steps_accepts_object_words(tmp_path: Path) -> None:
    """Whisper SDK historically returned objects (not dicts) — handle both."""

    class _W:
        def __init__(self, w: str, s: float, e: float) -> None:
            self.word = w
            self.start = s
            self.end = e

    audio = tmp_path / "a.mp3"
    _write_dummy_audio(audio)
    fake_words = [_W("hello", 0.0, 0.5), _W("world", 0.6, 1.2)]
    client = _FakeOpenAIClient(fake_words)
    timings = pf_align.whisper_align_steps(
        audio, _steps("Hello world."), openai_client=client
    )
    assert timings[0].start_ms == 0
    assert timings[0].end_ms == 1200


# ---------------------------------------------------------------------------
# synthesize_full_narration — verifies single TTS call with joined text
# ---------------------------------------------------------------------------


def test_synthesize_full_narration_joins_lines_and_calls_tts_once(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Path, str, str]] = []

    def fake_tts(text: str, out: Path, *, voice: str, model: str) -> None:
        calls.append((text, out, voice, model))
        out.write_bytes(b"mp3-bytes")

    out = tmp_path / "n.mp3"
    transcript = pf_align.synthesize_full_narration(
        _steps("Open page", "Click button"),
        out,
        voice="coral",
        model="gpt-4o-mini-tts",
        tts_synthesize=fake_tts,
    )
    assert len(calls) == 1
    text, path, voice, model = calls[0]
    assert text == "Open page. Click button."
    assert path == out
    assert voice == "coral"
    assert model == "gpt-4o-mini-tts"
    assert transcript == "Open page. Click button."
    assert out.exists()


def test_synthesize_full_narration_raises_for_empty_steps(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="no steps"):
        pf_align.synthesize_full_narration(
            [],
            tmp_path / "x.mp3",
            voice="coral",
            model="gpt-4o-mini-tts",
            tts_synthesize=lambda *a, **k: None,  # type: ignore[arg-type]
        )
