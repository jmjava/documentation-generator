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


def _verdict_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _verdict_reason(lines: list[str]) -> str:
    if len(lines) > 1:
        return lines[1]
    return lines[0]


def _unparsed_verdict(text: str) -> ImageReviewResult:
    preview = (text or "").strip()
    if len(preview) > 80:
        preview = preview[:77] + "..."
    return ImageReviewResult(False, f"vision review reply was not PASS/FAIL: {preview!r}")


def parse_review_verdict(text: str) -> ImageReviewResult:
    """Parse a PASS/FAIL vision reply. Unparseable text fails closed."""
    lines = _verdict_lines(text)
    if not lines:
        return ImageReviewResult(False, "vision review returned empty text")
    verdict = lines[0].split()[0].upper().strip(".:")
    reason = _verdict_reason(lines)
    if verdict == "PASS":
        return ImageReviewResult(True, reason)
    if verdict == "FAIL":
        return ImageReviewResult(False, reason)
    return _unparsed_verdict(text)


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


# Visual-style words an image prompt may use without being documented terms.
_IMAGE_STYLE_TOKENS = frozenset(
    """
    diagram diagrams illustration illustrations icon icons flat clean vector
    isometric cartoon watercolor sketch photo photographic realistic abstract
    artwork image images picture pictures visual background foreground style
    colored colour color palette high contrast simple minimal educational
    documentary video watermark signature logo logos chrome banner poster
    scene board rounded pill diamond arrow arrows flow flowchart infographic
    thumbnail render rendering drawing draw depict showing shows show
    depicting depicts labeled labelled label labels text white black blue
    green orange red gray grey dark light bright soft hard wide tall small
    large tiny big thin thick line lines box boxes node nodes panel panels
    layout grid row rows column columns
    """.split()
)


def _optional_bool(cfg: "Config", block: dict, key: str, label: str) -> bool | None:
    if key not in block or block.get(key) is None:
        return None
    from docgen.config import require_yaml_bool

    return require_yaml_bool(block[key], label=label, source=cfg._source_label())


def align_with_docs(cfg: "Config") -> bool:
    """Default true. ``image_generation.align_with_docs`` must be a YAML bool."""
    block = cfg._block("image_generation")
    flag = _optional_bool(cfg, block, "align_with_docs", "image_generation.align_with_docs")
    if flag is None:
        return True
    return flag


def align_review_enabled(cfg: "Config") -> bool:
    block = cfg._block("image_generation")
    flag = _optional_bool(cfg, block, "align_review", "image_generation.align_review")
    if flag is None:
        return True
    return flag


def image_prompt_alignment_enabled(cfg: "Config") -> bool:
    block = cfg._sub_block(
        cfg._block("validation"),
        "image_prompt_alignment",
        label="validation.image_prompt_alignment",
    )
    flag = _optional_bool(
        cfg, block, "enabled", "validation.image_prompt_alignment.enabled"
    )
    if flag is None:
        return True
    return flag


def image_asset_alignment_settings(cfg: "Config") -> dict:
    """OCR on by default; vision review off unless ``review: true``."""
    block = cfg._sub_block(
        cfg._block("validation"),
        "image_asset_alignment",
        label="validation.image_asset_alignment",
    )
    enabled = _optional_bool(cfg, block, "enabled", "validation.image_asset_alignment.enabled")
    ocr = _optional_bool(cfg, block, "ocr", "validation.image_asset_alignment.ocr")
    review = _optional_bool(cfg, block, "review", "validation.image_asset_alignment.review")
    return {
        "enabled": True if enabled is None else enabled,
        "ocr": True if ocr is None else ocr,
        "review": False if review is None else review,
    }


def _prompt_preview(prompt: str) -> str:
    if len(prompt) <= 80:
        return prompt
    return prompt[:77] + "..."


def _prompt_alignment_issue(el: dict, corpus: set[str]) -> str | None:
    from docgen.scene_spec import content_tokens

    rel = str(el.get("image") or "").strip() or "(unnamed image)"
    prompt = str(el.get("prompt") or "").strip()
    if not prompt:
        return None
    substance = content_tokens(prompt) - _IMAGE_STYLE_TOKENS
    if not substance:
        return f"{rel}: image prompt is only visual style (no documented subject terms)"
    if substance & corpus:
        return None
    preview = _prompt_preview(prompt)
    return (
        f"{rel}: image prompt shares no documented terms with "
        f"narration/source: {preview!r}"
    )


def image_prompt_alignment_violations(
    spec: dict,
    *,
    corpus_text: str,
) -> list[str]:
    """Reject image prompts that share no documented terms with narration/source."""
    from docgen.scene_spec import content_tokens, iter_image_elements

    elements = iter_image_elements(spec)
    if not elements:
        return []
    corpus = content_tokens(corpus_text)
    if not corpus:
        return []
    issues: list[str] = []
    for el in elements:
        issue = _prompt_alignment_issue(el, corpus)
        if issue:
            issues.append(issue)
    return issues


def _confident_invented(ocr_text: str, corpus: set[str]) -> set[str]:
    from docgen.scene_spec import content_tokens

    substance = content_tokens(ocr_text) - _IMAGE_STYLE_TOKENS
    invented = {token for token in substance if token not in corpus}
    return {token for token in invented if len(token) >= 4}


def _ocr_should_fail(confident: set[str]) -> bool:
    if len(confident) >= 2:
        return True
    return any(len(token) >= 6 for token in confident)


def image_ocr_alignment_violations(
    ocr_text: str,
    *,
    corpus_text: str,
    relpath: str = "image",
) -> list[str]:
    """Reject OCR tokens that look like invented documented terms."""
    from docgen.scene_spec import content_tokens

    corpus = content_tokens(corpus_text)
    if not corpus:
        return []
    confident = _confident_invented(ocr_text, corpus)
    if not _ocr_should_fail(confident):
        return []
    sample = ", ".join(repr(token) for token in sorted(confident)[:6])
    return [f"{relpath}: on-image OCR has terms not in narration/source: {sample}"]


def _load_spec_mapping(path: Path) -> tuple[dict | None, str | None]:
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, f"could not load {path.name}: {exc}"
    if isinstance(raw, dict):
        return raw, None
    return None, f"{path.name}: root must be a mapping"


def _asset_ocr_issues(asset: Path, rel: str, corpus: str, ocr_on: bool) -> list[str]:
    if not ocr_on:
        return []
    ocr_text = ocr_image_text(asset)
    if ocr_text is None:
        return [f"{rel}: could not OCR image (unreadable file)"]
    if not ocr_text:
        return []
    return image_ocr_alignment_violations(ocr_text, corpus_text=corpus, relpath=rel)


def _asset_review_issues(
    asset: Path,
    el: dict,
    corpus: str,
    cfg: "Config",
    review_on: bool,
) -> list[str]:
    if not review_on:
        return []
    rel = str(el.get("image") or "").strip()
    verdict = review_image_against_docs(
        asset,
        corpus_text=corpus,
        authored_prompt=str(el.get("prompt") or ""),
        label=str(el.get("label") or ""),
        cfg=cfg,
    )
    if verdict.passed:
        return []
    return [f"{rel}: vision review FAIL — {verdict.reason}"]


def _pixel_issues_for_spec(cfg: "Config", raw: dict, settings: dict) -> list[str]:
    from docgen.image_generate import collect_alignment_corpus
    from docgen.scene_spec import iter_image_elements

    corpus = collect_alignment_corpus(cfg, raw)
    if not corpus.strip():
        return []
    issues: list[str] = []
    for el in iter_image_elements(raw):
        rel = str(el.get("image") or "").strip()
        if not rel:
            continue
        asset = cfg.base_dir / rel
        if not asset.is_file():
            continue
        issues.extend(_asset_ocr_issues(asset, rel, corpus, bool(settings.get("ocr", True))))
        issues.extend(_asset_review_issues(asset, el, corpus, cfg, bool(settings.get("review"))))
    return issues


def image_doc_alignment_issues(cfg: "Config", seg_id: str) -> list[str]:
    """Prompt and pixel issues for one segment. Empty when there is nothing to score.

    Folded into ``scene_assets`` so validate fails closed without a new check name.
    """
    from docgen.image_generate import collect_alignment_corpus

    if not image_prompt_alignment_enabled(cfg) and not image_asset_alignment_settings(cfg)["enabled"]:
        return []
    seg_name = cfg.resolve_segment_name(seg_id)
    spec_path = cfg.animations_dir / "specs" / f"{seg_name}.scene.yaml"
    if not spec_path.is_file():
        return []
    raw, err = _load_spec_mapping(spec_path)
    if err:
        return [err]
    assert raw is not None
    issues: list[str] = []
    if image_prompt_alignment_enabled(cfg):
        corpus = collect_alignment_corpus(cfg, raw)
        issues.extend(image_prompt_alignment_violations(raw, corpus_text=corpus))
    asset_settings = image_asset_alignment_settings(cfg)
    if asset_settings["enabled"]:
        issues.extend(_pixel_issues_for_spec(cfg, raw, asset_settings))
    return issues
