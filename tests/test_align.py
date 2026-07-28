"""Tests for docgen.align — local (no-Whisper) narration ↔ audio alignment."""

from __future__ import annotations

import pytest

from docgen.align import (
    build_local_timing,
    parse_silencedetect_output,
    reconcile_intervals_to_sentences,
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

    def test_pause_aware_weights_give_punctuated_tokens_more_span(self) -> None:
        # "Hello," should claim a larger share than "Hi" of equal letter length.
        timing = build_local_timing("Hi Hello,", 4.0, [(0.0, 4.0)])
        words = {w["word"]: w for w in timing["words"]}
        hi_span = words["Hi"]["end"] - words["Hi"]["start"]
        hello_span = words["Hello,"]["end"] - words["Hello,"]["start"]
        assert hello_span > hi_span

    def test_reconcile_merges_extra_intervals_toward_sentence_count(self) -> None:
        # Three intervals for two sentences → merge shortest gap.
        ivs = [(0.0, 1.0), (1.1, 2.0), (3.0, 5.0)]
        out = reconcile_intervals_to_sentences(ivs, 2)
        assert len(out) == 2
        assert out[0] == (0.0, 2.0)
        assert out[1] == (3.0, 5.0)

    def test_build_local_timing_uses_reconcile_for_near_miss_counts(self) -> None:
        text = "First sentence here. Second sentence follows."
        # Three speech intervals for two sentences — should still 1:1 after merge.
        timing = build_local_timing(
            text, 6.0, [(0.0, 2.0), (2.1, 3.5), (4.0, 6.0)]
        )
        assert len(timing["segments"]) == 2
        assert timing["segments"][0]["start"] == pytest.approx(0.0)
        assert timing["segments"][0]["end"] == pytest.approx(3.5)
        assert timing["segments"][1]["start"] == pytest.approx(4.0)
