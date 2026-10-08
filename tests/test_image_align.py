"""Pixel-level image alignment: OCR verdicts and vision PASS/FAIL parsing."""

from __future__ import annotations

from pathlib import Path

from docgen.image_align import (
    build_review_user_message,
    parse_review_verdict,
    review_image_against_docs,
)


def test_parse_review_verdict_pass_and_fail() -> None:
    ok = parse_review_verdict("PASS\nDepicts the checkout service lock.")
    assert ok.passed is True
    assert "checkout" in ok.reason
    bad = parse_review_verdict("FAIL\nShows a WidgetX console instead.")
    assert bad.passed is False
    assert "WidgetX" in bad.reason


def test_parse_review_verdict_unparseable_fails_closed() -> None:
    out = parse_review_verdict("looks fine to me")
    assert out.passed is False
    assert "PASS/FAIL" in out.reason


def test_parse_review_verdict_empty_fails_closed() -> None:
    out = parse_review_verdict("   ")
    assert out.passed is False


def test_build_review_user_message_includes_docs() -> None:
    msg = build_review_user_message(
        corpus_text="The checkout service owns the cart lock.",
        authored_prompt="clean diagram of the checkout service",
        label="checkout service",
    )
    assert "DOCUMENTED SUBJECT" in msg
    assert "cart lock" in msg
    assert "AUTHORED IMAGE PROMPT" in msg
    assert "ON-SCREEN LABEL" in msg


def test_review_image_against_docs_uses_chat_fn(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    captured: dict = {}

    def _chat(**kwargs: object) -> str:
        captured.update(kwargs)
        return "PASS\nMatches the checkout service."

    verdict = review_image_against_docs(
        png,
        corpus_text="The checkout service owns the cart lock.",
        authored_prompt="diagram of checkout",
        chat_fn=_chat,
    )
    assert verdict.passed is True
    assert captured["image_bytes"] == png.read_bytes()
    assert "checkout service" in str(captured["user_message"])


def test_review_empty_file_fails(tmp_path: Path) -> None:
    png = tmp_path / "empty.png"
    png.write_bytes(b"")
    verdict = review_image_against_docs(
        png, corpus_text="checkout service", chat_fn=lambda **_k: "PASS\nok"
    )
    assert verdict.passed is False
    assert "empty" in verdict.reason
