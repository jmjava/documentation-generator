"""Local (offline) narration ↔ audio alignment — no speech recognition needed.

docgen authors the narration text itself, so producing ``timing.json`` is an
**alignment** problem, not a transcription problem:

1. The exact TTS input text comes from ``narration/<stem>.md``
   (via :func:`docgen.tts.markdown_to_tts_plain`).
2. The mp3 duration comes from ffprobe.
3. TTS engines pause at punctuation, so ``ffmpeg silencedetect`` recovers the
   real sentence boundaries from the audio.
4. Word-level ``start``/``end`` times are interpolated inside each speech
   interval proportionally to character length.

The output matches the Whisper-style ``timing.json`` contract
(``{"text", "segments": [...], "words": [...]}``), so ``wait_word``,
``scene-compile``, compose, and validation are unchanged. When the number of
detected speech intervals equals the number of sentences, each sentence is
mapped 1:1 onto its interval (near-exact boundaries); otherwise sentences are
distributed proportionally across the concatenated speech timeline.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_SILENCE_NOISE_DB = -35.0
DEFAULT_MIN_SILENCE_SEC = 0.3

# Ignore speech blips shorter than this when inverting silences.
_MIN_SPEECH_INTERVAL_SEC = 0.05

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[0-9]*\.?[0-9]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[0-9]*\.?[0-9]+)")


class AlignmentError(RuntimeError):
    """Raised when local alignment cannot run (missing ffmpeg, unreadable audio)."""


def split_sentences(text: str) -> list[str]:
    """Split narration plain text into spoken sentences (paragraphs then punctuation)."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        for sent in _SENTENCE_SPLIT_RE.split(para):
            sent = sent.strip()
            if sent:
                out.append(sent)
    return out


def parse_silencedetect_output(stderr: str, duration: float) -> list[tuple[float, float]]:
    """Invert ffmpeg ``silencedetect`` log lines into speech intervals over [0, duration]."""
    silences: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in stderr.splitlines():
        m = _SILENCE_START_RE.search(line)
        if m:
            pending_start = max(0.0, float(m.group(1)))
            continue
        m = _SILENCE_END_RE.search(line)
        if m and pending_start is not None:
            end = min(duration, float(m.group(1)))
            if end > pending_start:
                silences.append((pending_start, end))
            pending_start = None
    if pending_start is not None and pending_start < duration:
        silences.append((pending_start, duration))

    speech: list[tuple[float, float]] = []
    cursor = 0.0
    for s0, s1 in sorted(silences):
        if s0 - cursor >= _MIN_SPEECH_INTERVAL_SEC:
            speech.append((cursor, s0))
        cursor = max(cursor, s1)
    if duration - cursor >= _MIN_SPEECH_INTERVAL_SEC:
        speech.append((cursor, duration))
    if not speech and duration > 0:
        speech = [(0.0, duration)]
    return speech


def probe_duration(audio_path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except FileNotFoundError as exc:
        raise AlignmentError("ffprobe not found in PATH (required for local timing)") from exc
    except (ValueError, subprocess.TimeoutExpired) as exc:
        raise AlignmentError(f"cannot probe duration of {audio_path}: {exc}") from exc


def detect_speech_intervals(
    audio_path: Path,
    duration: float,
    *,
    noise_db: float = DEFAULT_SILENCE_NOISE_DB,
    min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
) -> list[tuple[float, float]]:
    """Run ffmpeg silencedetect and return speech (non-silent) intervals."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_sec}",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:
        raise AlignmentError("ffmpeg not found in PATH (required for local timing)") from exc
    except subprocess.TimeoutExpired as exc:
        raise AlignmentError(f"ffmpeg silencedetect timed out on {audio_path}") from exc
    return parse_silencedetect_output(proc.stderr or "", duration)


def _speech_timeline_mapper(
    intervals: list[tuple[float, float]],
) -> tuple[float, Any]:
    """Total speech seconds + mapper from speech-time offset → wall-clock time."""
    total = sum(e - s for s, e in intervals)

    def to_wall(t_speech: float) -> float:
        remaining = max(0.0, t_speech)
        for s, e in intervals:
            span = e - s
            if remaining <= span:
                return s + remaining
            remaining -= span
        return intervals[-1][1] if intervals else 0.0

    return total, to_wall


def _token_weight(tok: str) -> float:
    """Character weight with a pause bump for trailing punctuation (TTS breath).

    Commas / semicolons / colons and sentence-final punctuation get a small
    extra share of the span so word ``start`` times land slightly earlier —
    closer to real TTS pacing than pure character-proportional splits.
    """
    base = float(max(len(tok), 1))
    if tok.endswith(("...", "…")):
        return base + 2.2
    if tok.endswith((".", "!", "?")):
        return base + 1.4
    if tok.endswith((",", ";", ":")):
        return base + 0.8
    if tok.endswith(("-", "—", "–")):
        return base + 0.5
    return base


def _words_for_span(sentence: str, start: float, end: float) -> list[dict[str, Any]]:
    toks = sentence.split()
    if not toks:
        return []
    span = max(0.0, end - start)
    weights = [_token_weight(t) for t in toks]
    weight_total = sum(weights) or 1.0
    out: list[dict[str, Any]] = []
    cursor = start
    for tok, w in zip(toks, weights):
        w_span = span * w / weight_total
        out.append(
            {"start": round(cursor, 3), "end": round(cursor + w_span, 3), "word": tok}
        )
        cursor += w_span
    if out:
        out[-1]["end"] = round(end, 3)
    return out


def _merge_nearest_intervals(
    intervals: list[tuple[float, float]], target: int
) -> list[tuple[float, float]]:
    """Merge shortest gaps until ``len(intervals) == target`` (when over-segmented)."""
    ivs = list(intervals)
    if target < 1 or len(ivs) <= target:
        return ivs
    while len(ivs) > target:
        # Merge the pair with the smallest inter-interval gap (silence between).
        best_i = 0
        best_gap = float("inf")
        for i in range(len(ivs) - 1):
            gap = ivs[i + 1][0] - ivs[i][1]
            if gap < best_gap:
                best_gap = gap
                best_i = i
        a0, _a1 = ivs[best_i]
        _b0, b1 = ivs[best_i + 1]
        ivs = ivs[:best_i] + [(a0, b1)] + ivs[best_i + 2 :]
    return ivs


def reconcile_intervals_to_sentences(
    intervals: list[tuple[float, float]], n_sentences: int
) -> list[tuple[float, float]]:
    """Nudge speech-interval count toward sentence count for 1:1 mapping.

    When silencedetect finds a few **extra** pauses vs punctuation, merge the
    nearest gaps so we keep the high-accuracy 1:1 path. Under-segmented audio
    (fewer intervals than sentences — including a single continuous interval)
    stays on the proportional path, which uses pause-aware sentence weights.
    """
    if n_sentences < 1 or not intervals:
        return intervals
    ivs = list(intervals)
    if len(ivs) == n_sentences:
        return ivs
    if len(ivs) > n_sentences:
        # Only reconcile when close (small silence over-detection).
        if len(ivs) - n_sentences <= max(2, n_sentences // 3):
            return _merge_nearest_intervals(ivs, n_sentences)
        return ivs
    return ivs


def build_local_timing(
    text: str,
    duration: float,
    speech_intervals: list[tuple[float, float]],
) -> dict[str, Any]:
    """Whisper-shaped timing block from known text + measured speech intervals."""
    sentences = split_sentences(text)
    if not sentences or duration <= 0:
        return {"text": text, "segments": [], "words": []}

    intervals = [iv for iv in speech_intervals if iv[1] > iv[0]] or [(0.0, duration)]
    intervals = reconcile_intervals_to_sentences(intervals, len(sentences))

    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []

    if len(intervals) == len(sentences):
        # High-accuracy path: TTS paused once per sentence boundary.
        for sent, (s0, s1) in zip(sentences, intervals):
            segments.append({"start": round(s0, 3), "end": round(s1, 3), "text": sent})
            words.extend(_words_for_span(sent, s0, s1))
    else:
        # Proportional path: allocate each sentence a pause-aware weighted slice
        # of the concatenated speech timeline (silences are skipped by the mapper).
        total_speech, to_wall = _speech_timeline_mapper(intervals)
        weights = [sum(_token_weight(t) for t in s.split()) or 1.0 for s in sentences]
        total_w = sum(weights)
        cursor = 0.0
        for sent, w in zip(sentences, weights):
            span = total_speech * w / total_w
            s0 = to_wall(cursor)
            s1 = to_wall(cursor + span)
            segments.append({"start": round(s0, 3), "end": round(s1, 3), "text": sent})
            words.extend(_words_for_span(sent, s0, s1))
            cursor += span

    if segments:
        segments[-1]["end"] = round(min(segments[-1]["end"], duration), 3)
    if words:
        words[-1]["end"] = round(min(words[-1]["end"], duration), 3)
    return {"text": text, "segments": segments, "words": words}


def align_narration_to_audio(
    text: str,
    audio_path: Path,
    *,
    noise_db: float = DEFAULT_SILENCE_NOISE_DB,
    min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
) -> dict[str, Any]:
    """End-to-end local alignment: probe duration, detect speech, build timing block."""
    duration = probe_duration(audio_path)
    intervals = detect_speech_intervals(
        audio_path, duration, noise_db=noise_db, min_silence_sec=min_silence_sec
    )
    return build_local_timing(text, duration, intervals)
