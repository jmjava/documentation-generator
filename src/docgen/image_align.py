"""Pixel-level alignment of generated scene images against documentation.

Prompt grounding (``image_prompt_alignment``) only checks the caption. This
module looks at the **PNG**:

* **OCR** — readable tokens that are not in narration/source fail (invented
  on-image labels). Empty OCR is fine (many diagrams have no text).
* **Vision review** — a chat model that accepts images (OpenAI, Grok, or
  Claude) answers PASS/FAIL against the same documentation corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from docgen.config import Config

DEFAULT_REVIEW_MODEL = "gpt-4o"

_REVIEW_SYSTEM = """You review one illustration for a documentation video.

Decide whether the IMAGE depicts the DOCUMENTED SUBJECT (narration + source).
PASS when the picture is a reasonable, simplified depiction of those concepts.
FAIL when it shows a different subject, invented product/API names, decorative
text that is not copied from the docs, fake UI chrome, or generic clip-art
unrelated to the documentation.

Reply with EXACTLY two lines and nothing else:
PASS
<one short reason>
or
FAIL
<one short reason naming the mismatch or invented label>
"""


@dataclass(frozen=True)
class ImageReviewResult:
    passed: bool
    reason: str
    ocr_text: str = ""


def ocr_image_text(path: Path) -> str | None:
    """OCR a still image. ``None`` if unreadable or tesseract is unavailable.

    Empty string means the file decoded but no text was found.
    """
    try:
        import cv2
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        return None
    img = cv2.imread(str(path))
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    try:
        return str(pytesseract.image_to_string(thresh) or "")
    except Exception:
        return None


def parse_review_verdict(text: str) -> ImageReviewResult:
    """Parse a PASS/FAIL vision reply. Unparseable text fails closed."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ImageReviewResult(False, "vision review returned empty text")
    verdict = lines[0].split()[0].upper().strip(".:")
    reason = lines[1] if len(lines) > 1 else " ".join(lines[1:]) or lines[0]
    if verdict == "PASS":
        return ImageReviewResult(True, reason)
    if verdict == "FAIL":
        return ImageReviewResult(False, reason)
    preview = (text or "").strip()
    if len(preview) > 80:
        preview = preview[:77] + "..."
    return ImageReviewResult(False, f"vision review reply was not PASS/FAIL: {preview!r}")


def build_review_user_message(
    *,
    corpus_text: str,
    authored_prompt: str = "",
    label: str = "",
) -> str:
    parts = [
        "DOCUMENTED SUBJECT:",
        (corpus_text or "").strip() or "(none)",
    ]
    if (authored_prompt or "").strip():
        parts.extend(["", "AUTHORED IMAGE PROMPT:", authored_prompt.strip()])
    if (label or "").strip():
        parts.extend(["", "ON-SCREEN LABEL:", label.strip()])
    parts.extend(["", "Review the attached image."])
    return "\n".join(parts)


def _media_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")


def review_image_against_docs(
    path: Path,
    *,
    corpus_text: str,
    authored_prompt: str = "",
    label: str = "",
    cfg: "Config | None" = None,
    model: str = "",
    chat_fn: Callable[..., str] | None = None,
) -> ImageReviewResult:
    """Send ``path`` + documentation to a vision-capable chat model."""
    from docgen.ai_client import AIError, chat_completion_with_image

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return ImageReviewResult(False, f"could not read image {path}: {exc}")
    if not raw:
        return ImageReviewResult(False, f"image {path} is empty")
    user = build_review_user_message(
        corpus_text=corpus_text, authored_prompt=authored_prompt, label=label
    )
    invoke = chat_fn or chat_completion_with_image
    try:
        text = invoke(
            system_prompt=_REVIEW_SYSTEM,
            user_message=user,
            image_bytes=raw,
            media_type=_media_type_for(path),
            model=(model or "").strip() or DEFAULT_REVIEW_MODEL,
            temperature=0.0,
            cfg=cfg,
        )
    except (AIError, RuntimeError, OSError, TypeError, ValueError) as exc:
        return ImageReviewResult(False, f"vision review failed: {exc}")
    return parse_review_verdict(text)
