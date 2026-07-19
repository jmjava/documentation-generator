"""Tests for docgen.align — local (no-Whisper) narration ↔ audio alignment."""

from __future__ import annotations

import pytest

from docgen.align import (
    build_local_timing,
    parse_silencedetect_output,
    split_sentences,
)


class TestSplitSentences:
    def test_splits_on_terminal_punctuation(self) -> None:
        text = "First sentence. Second one! And a third?"
        assert split_sentences(text) == [
            "First sentence.",
            "Second one!",
            "And a third?",
        ]

    def test_paragraph_breaks_split(self) -> None:
        text = "Intro line\n\nBody continues here."
        assert split_sentences(text) == ["Intro line", "Body continues here."]

    def test_collapses_internal_whitespace(self) -> None:
        assert split_sentences("A  spaced   out sentence.") == ["A spaced out sentence."]

    def test_empty_text(self) -> None:
        assert split_sentences("   \n\n  ") == []


class TestParseSilencedetect:
    STDERR = """
[silencedetect @ 0x55] silence_start: 3.2
[silencedetect @ 0x55] silence_end: 4.0 | silence_duration: 0.8
[silencedetect @ 0x55] silence_start: 7.5
[silencedetect @ 0x55] silence_end: 8.1 | silence_duration: 0.6
"""

    def test_inverts_silences_to_speech(self) -> None:
        speech = parse_silencedetect_output(self.STDERR, duration=10.0)
        assert speech == [(0.0, 3.2), (4.0, 7.5), (8.1, 10.0)]

    def test_trailing_silence_without_end(self) -> None:
        stderr = "[silencedetect @ 0x55] silence_start: 9.0\n"
        speech = parse_silencedetect_output(stderr, duration=10.0)
        assert speech == [(0.0, 9.0)]

    def test_no_silences_yields_full_interval(self) -> None:
        assert parse_silencedetect_output("", duration=12.0) == [(0.0, 12.0)]


class TestBuildLocalTiming:
    def test_one_to_one_sentence_interval_mapping(self) -> None:
        text = "Alpha starts here. Beta follows after."
        intervals = [(0.0, 3.0), (4.0, 8.0)]
        timing = build_local_timing(text, 8.0, intervals)

        assert [s["text"] for s in timing["segments"]] == [
            "Alpha starts here.",
            "Beta follows after.",
        ]
        assert timing["segments"][0]["start"] == pytest.approx(0.0)
        assert timing["segments"][0]["end"] == pytest.approx(3.0)
        assert timing["segments"][1]["start"] == pytest.approx(4.0)
        assert timing["segments"][1]["end"] == pytest.approx(8.0)

        words = timing["words"]
        assert [w["word"] for w in words[:3]] == ["Alpha", "starts", "here."]
        # First word of sentence 2 starts exactly at its speech interval.
        beta = next(w for w in words if w["word"] == "Beta")
        assert beta["start"] == pytest.approx(4.0)

    def test_proportional_fallback_single_interval(self) -> None:
        text = "Short one. This second sentence is much much longer than the first."
        timing = build_local_timing(text, 10.0, [(0.0, 10.0)])
        segs = timing["segments"]
        assert len(segs) == 2
        # Longer sentence gets the larger share of the timeline.
        assert (segs[1]["end"] - segs[1]["start"]) > (segs[0]["end"] - segs[0]["start"])
        assert segs[0]["start"] == pytest.approx(0.0)
        assert segs[-1]["end"] == pytest.approx(10.0)

    def test_words_are_monotonic_and_bounded(self) -> None:
        text = "One two three. Four five six seven. Eight nine."
        timing = build_local_timing(text, 9.0, [(0.0, 2.5), (3.0, 6.0), (6.5, 9.0)])
        words = timing["words"]
        starts = [w["start"] for w in words]
        assert starts == sorted(starts)
        assert all(0.0 <= w["start"] <= w["end"] <= 9.0 for w in words)

    def test_empty_text_or_zero_duration(self) -> None:
        assert build_local_timing("", 10.0, [(0.0, 10.0)])["words"] == []
        assert build_local_timing("Hello there.", 0.0, [])["segments"] == []

    def test_timing_json_shape_matches_whisper_contract(self) -> None:
        timing = build_local_timing("Hello world.", 2.0, [(0.0, 2.0)])
        assert set(timing.keys()) == {"text", "segments", "words"}
        for s in timing["segments"]:
            assert set(s.keys()) == {"start", "end", "text"}
        for w in timing["words"]:
            assert set(w.keys()) == {"start", "end", "word"}
