"""Image generation for scene-spec **image elements** (OpenAI or xAI Imagine).

A ``*.scene.yaml`` box may be an image element::

    boxes:
      - image: images/architecture.png   # bundle-relative asset path
        width: 6.0
        height: 3.2
        prompt: "Clean flat diagram of ..."   # used by `docgen image-generate`
        label: architecture                    # optional Whisper timing anchor

``docgen image-generate`` scans specs, calls the Images API (OpenAI or xAI Imagine)
for elements whose asset is missing (or ``--force``), and writes PNG bytes to
``<bundle>/<image path>``. By default the authored ``prompt`` is **grounded** in
the segment narration plus ``manim_scene_generation`` source snippets so the
image model sees the documentation, not only a short caption. Prompts that
share no documented terms fail closed (same check as ``validate`` /
``image_prompt_alignment``). After the PNG is written, **OCR** rejects
invented on-image labels and a **vision review** (OpenAI / Grok / Claude)
checks the pixels against the same corpus (``image_generation.align_review``).
A failed review retries once with the critique, then deletes the asset.
``docgen manim`` then loads the asset via the ``_image`` helper in ``scenes.py``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from docgen.image_align import (
    ImageReviewResult,
    image_ocr_alignment_violations,
    image_prompt_alignment_violations,
    ocr_image_text,
    review_image_against_docs,
)
from docgen.openai_retry import call_with_rate_limit_retries
from docgen.scene_spec import (
    iter_image_elements,
    load_scene_spec,
)

if TYPE_CHECKING:
    from docgen.config import Config

DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1536x1024"
DEFAULT_IMAGE_STYLE = (
    "Clean educational diagram for a documentation video. Flat vector "
    "illustration, high contrast, no watermark, no signature, no decorative "
    "fake UI or invented product logos. Any readable text must be short ASCII "
    "copied from the documented subject. Do not add components that are not "
    "named in the documentation."
)
_ALIGN_CORPUS_EXCERPT = 2200


class ImageGenerationError(RuntimeError):
    """Raised when an image asset cannot be produced (bad path, no prompt, API failure)."""


@dataclass(frozen=True)
class ImageAssetResult:
    relpath: str
    path: Path
    status: str  # "generated" | "exists" | "dry-run"
    prompt: str
    effective_prompt: str = ""


def generate_image_bytes(
    *,
    prompt: str,
    model: str,
    size: str,
    quality: str | None = None,
    cfg: "Config | None" = None,
) -> bytes:
    """Call the Images API (OpenAI or xAI Imagine) and return decoded PNG bytes."""
    import openai

    from docgen.ai_client import (
        fetch_url_bytes,
        openai_client,
        resolve_ai_settings,
        resolve_image_model,
    )

    settings = resolve_ai_settings(cfg)
    if settings.is_anthropic:
        raise ImageGenerationError(
            "Anthropic has no image API. Use OPENAI_API_KEY / CURSOR_API_KEY "
            "(ai.provider: openai) or XAI_API_KEY (ai.provider: grok) for "
            f"`docgen image-generate`. {settings.auth_help()}"
        )
    resolved = resolve_image_model(model, settings)
    client = openai_client(cfg)
    kwargs: dict = {"model": resolved, "prompt": prompt, "n": 1}
    if not settings.is_grok:
        kwargs["size"] = size
        if quality:
            kwargs["quality"] = quality
        # dall-e models return URLs unless b64 is requested; gpt-image-1 is b64-only.
        if resolved.startswith("dall-e"):
            kwargs["response_format"] = "b64_json"

    try:
        response = call_with_rate_limit_retries(lambda: client.images.generate(**kwargs))
    except openai.AuthenticationError as exc:
        raise ImageGenerationError(
            f"{'xAI' if settings.is_grok else 'OpenAI'} rejected {settings.api_key_env} "
            f"(authentication failed): {exc}. {settings.auth_help()} "
            "Or use --dry-run to inspect prompts only."
        ) from exc
    except openai.PermissionDeniedError as exc:
        raise ImageGenerationError(
            f"{'xAI' if settings.is_grok else 'OpenAI'} permission denied for image model "
            f"{resolved!r}: {exc}. Pick a model your account may use, or set "
            "image_generation.model in docgen.yaml."
        ) from exc
    except openai.APIConnectionError as exc:
        raise ImageGenerationError(
            f"{'xAI' if settings.is_grok else 'OpenAI'} connection error: {exc} — "
            "re-run when connectivity is restored."
        ) from exc

    data = response.data[0] if response.data else None
    b64 = getattr(data, "b64_json", None) if data is not None else None
    if b64:
        raw = base64.b64decode(b64)
        if not raw:
            raise ImageGenerationError(
                f"Image model {resolved!r} returned empty b64_json bytes"
            )
        return raw
    url = getattr(data, "url", None) if data is not None else None
    if url:
        try:
            raw = fetch_url_bytes(str(url))
        except Exception as exc:
            raise ImageGenerationError(
                f"Image model {resolved!r} returned a URL but download failed: {exc}."
            ) from exc
        if not raw:
            raise ImageGenerationError(
                f"Image model {resolved!r} URL download was empty"
            )
        return raw
    raise ImageGenerationError(
        f"Image response for model {resolved!r} had neither b64_json nor url; "
        "cannot write the asset."
    )


def _excerpt(text: str, limit: int = _ALIGN_CORPUS_EXCERPT) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def build_aligned_image_prompt(
    authored: str,
    *,
    corpus_text: str = "",
    label: str = "",
    style: str = DEFAULT_IMAGE_STYLE,
) -> str:
    """Wrap an authored scene-spec prompt with documentation + style constraints."""
    parts: list[str] = [(style or "").strip() or DEFAULT_IMAGE_STYLE, ""]
    corpus = (corpus_text or "").strip()
    if corpus:
        parts.append(
            "Documented subject (use these terms; do not invent names, logos, "
            "or extra components):"
        )
        parts.append(_excerpt(corpus))
        parts.append("")
    lab = (label or "").strip()
    if lab:
        parts.append(f"On-screen timing label (must remain accurate): {lab}")
        parts.append("")
    parts.append("Illustration request:")
    parts.append((authored or "").strip())
    return "\n".join(parts).strip() + "\n"


def _narration_corpus_part(cfg: "Config", seg_id: str) -> str:
    found = cfg.find_segment_asset(cfg.narration_dir, seg_id, ".md")
    if found is None or not found.is_file():
        return ""
    try:
        return found.read_text(encoding="utf-8")
    except OSError:
        return ""


def _hint_source_parts(cfg: "Config", seg_id: str) -> list[str]:
    from docgen.manim_scene_support import (
        collect_source_snippets,
        merged_scene_generation_settings,
    )

    settings = merged_scene_generation_settings(cfg, seg_id)
    parts: list[str] = []
    for hint in settings.hints:
        if str(hint).strip():
            parts.append(str(hint).strip())
    for label, text in collect_source_snippets(cfg, settings, extra_paths=[]):
        body = str(text or "").strip()
        if body:
            parts.append(f"{label}\n{body}")
    return parts


def collect_alignment_corpus(cfg: "Config", spec: dict[str, Any]) -> str:
    """Narration + scene-generation hints + source snippets for one spec."""
    seg_id = str(spec.get("segment_id") or "").strip()
    if not seg_id:
        return ""
    parts: list[str] = []
    narration = _narration_corpus_part(cfg, seg_id)
    if narration:
        parts.append(narration)
    parts.extend(_hint_source_parts(cfg, seg_id))
    return "\n\n".join(part for part in parts if str(part).strip())


def _resolve_asset_path(cfg: "Config", relpath: str) -> Path:
    p = Path(relpath)
    if p.is_absolute() or ".." in p.parts:
        raise ImageGenerationError(
            f"image path {relpath!r} must be relative to the bundle directory "
            "(no absolute paths or '..')"
        )
    return cfg.base_dir / p


def _review_retry_count(cfg: "Config") -> int:
    block = cfg._block("image_generation")
    raw = block.get("align_review_retries")
    if raw is None:
        return 1
    from docgen.config import require_yaml_number

    return max(0, int(require_yaml_number(
        raw, label="image_generation.align_review_retries", source=cfg._source_label()
    )))


def _override_or(override: str | None, configured: object, default: str) -> str:
    chosen = (override or "").strip()
    if chosen:
        return chosen
    text = str(configured or "").strip()
    if text:
        return text
    return default


def _optional_quality(configured: object) -> str | None:
    if not configured:
        return None
    text = str(configured).strip()
    if text:
        return text
    return None


def _image_job(cfg: "Config", model_override: str | None, size_override: str | None) -> dict[str, Any]:
    from docgen.image_align import align_review_enabled, align_with_docs

    icfg = cfg.image_generation_config
    return {
        "model": _override_or(model_override, icfg.get("model"), DEFAULT_IMAGE_MODEL),
        "size": _override_or(size_override, icfg.get("size"), DEFAULT_IMAGE_SIZE),
        "quality": _optional_quality(icfg.get("quality")),
        "align": align_with_docs(cfg),
        "align_review": align_review_enabled(cfg),
        "pixel_retries": _review_retry_count(cfg),
        "review_model": str(icfg.get("review_model") or "").strip(),
        "style": _override_or(None, icfg.get("style"), DEFAULT_IMAGE_STYLE),
    }


def _live_review(
    align: bool,
    align_review: bool,
    review_fn: Callable[..., ImageReviewResult] | None,
    image_fn: Callable[[str], bytes] | None,
) -> bool:
    if not align:
        return False
    if not align_review:
        return False
    if review_fn is not None:
        return True
    return image_fn is None


def _reject_unaligned_prompts(spec_path: Path, spec: dict[str, Any], corpus: str, align: bool) -> None:
    if not align:
        return
    issues = image_prompt_alignment_violations(spec, corpus_text=corpus)
    if not issues:
        return
    joined = "\n  ".join(issues)
    raise ImageGenerationError(
        f"{spec_path}: image prompt alignment failed — rewrite each "
        f"`prompt` so it uses documented terms from narration/source "
        f"(or set image_generation.align_with_docs: false):\n  {joined}"
    )


def _effective_prompt(prompt: str, *, align: bool, corpus: str, label: str, style: str) -> str:
    if align and prompt:
        return build_aligned_image_prompt(prompt, corpus_text=corpus, label=label, style=style)
    return prompt


def _existing_or_dry(
    *,
    spec_path: Path,
    rel: str,
    out: Path,
    prompt: str,
    effective: str,
    force: bool,
    dry_run: bool,
) -> ImageAssetResult | None:
    if out.is_file() and not force:
        return ImageAssetResult(rel, out, "exists", prompt, effective)
    if not prompt:
        raise ImageGenerationError(
            f"{spec_path}: image element {rel!r} has no `prompt` and the asset is missing "
            f"({out}); add the file to the bundle or set a prompt in the spec."
        )
    if dry_run:
        return ImageAssetResult(rel, out, "dry-run", prompt, effective)
    return None


def _prompt_with_critique(effective: str, critique: str) -> str:
    if not critique:
        return effective
    return (
        f"{effective}\n\n--- PIXEL REVIEW FAILED ---\n{critique}\n"
        "Redraw so the image matches the documented subject. "
        "Do not invent labels or extra components."
    )


def _write_or_raise(spec_path: Path, rel: str, out: Path, data: bytes) -> None:
    if not data:
        raise ImageGenerationError(
            f"{spec_path}: image element {rel!r} — provider returned empty bytes"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)


def _draw_until_aligned(
    *,
    spec_path: Path,
    rel: str,
    out: Path,
    prompt: str,
    effective: str,
    fn: Callable[[str], bytes],
    pixel_retries: int,
    pixel_kwargs: dict[str, Any],
) -> None:
    critique = ""
    last_issues: list[str] = []
    kept = False
    for _attempt in range(1 + pixel_retries):
        _write_or_raise(spec_path, rel, out, fn(_prompt_with_critique(effective, critique)))
        last_issues = _pixel_alignment_issues(out, relpath=rel, authored_prompt=prompt, **pixel_kwargs)
        if not last_issues:
            kept = True
            break
        critique = "\n".join(last_issues)
    if kept:
        return
    out.unlink(missing_ok=True)
    joined = "\n  ".join(last_issues)
    raise ImageGenerationError(
        f"{spec_path}: image {rel!r} failed pixel alignment "
        f"(OCR / vision review):\n  {joined}"
    )


def _one_image(
    cfg: "Config",
    spec_path: Path,
    el: dict[str, Any],
    *,
    job: dict[str, Any],
    corpus: str,
    force: bool,
    dry_run: bool,
    image_fn: Callable[[str], bytes] | None,
    review_fn: Callable[..., ImageReviewResult] | None,
    ocr_fn: Callable[[Path], str | None] | None,
) -> ImageAssetResult:
    rel = str(el["image"]).strip()
    prompt = str(el.get("prompt") or "").strip()
    out = _resolve_asset_path(cfg, rel)
    label = str(el.get("label") or "").strip()
    effective = _effective_prompt(
        prompt, align=job["align"], corpus=corpus, label=label, style=job["style"]
    )
    planned = _existing_or_dry(
        spec_path=spec_path,
        rel=rel,
        out=out,
        prompt=prompt,
        effective=effective,
        force=force,
        dry_run=dry_run,
    )
    if planned is not None:
        return planned
    fn = image_fn or (
        lambda p: generate_image_bytes(
            prompt=p, model=job["model"], size=job["size"], quality=job["quality"], cfg=cfg
        )
    )
    _draw_until_aligned(
        spec_path=spec_path,
        rel=rel,
        out=out,
        prompt=prompt,
        effective=effective,
        fn=fn,
        pixel_retries=job["pixel_retries"],
        pixel_kwargs={
            "corpus": corpus,
            "label": label,
            "cfg": cfg,
            "align": job["align"],
            "live_review": _live_review(job["align"], job["align_review"], review_fn, image_fn),
            "review_model": job["review_model"],
            "review_fn": review_fn,
            "ocr_fn": ocr_fn,
        },
    )
    return ImageAssetResult(rel, out, "generated", prompt, effective)


def generate_images_for_spec(
    cfg: "Config",
    spec_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    model_override: str | None = None,
    size_override: str | None = None,
    image_fn: Callable[[str], bytes] | None = None,
    review_fn: Callable[..., ImageReviewResult] | None = None,
    ocr_fn: Callable[[Path], str | None] | None = None,
) -> list[ImageAssetResult]:
    """Generate missing image assets referenced by one ``*.scene.yaml``.

    Existing assets are kept unless ``force``. An image element whose asset is
    missing **and** has no ``prompt`` fails loud — either commit the file or
    give the toolchain a prompt to generate it from.

    ``image_fn`` / ``review_fn`` / ``ocr_fn`` are injection points for tests.
    Live vision review runs when ``align_review`` is on and ``image_fn`` is
    not injected (or ``review_fn`` is provided).
    """
    spec = load_scene_spec(spec_path)
    job = _image_job(cfg, model_override, size_override)
    corpus = collect_alignment_corpus(cfg, spec) if job["align"] else ""
    _reject_unaligned_prompts(spec_path, spec, corpus, job["align"])
    return [
        _one_image(
            cfg,
            spec_path,
            el,
            job=job,
            corpus=corpus,
            force=force,
            dry_run=dry_run,
            image_fn=image_fn,
            review_fn=review_fn,
            ocr_fn=ocr_fn,
        )
        for el in iter_image_elements(spec)
    ]


def _pixel_alignment_issues(
    path: Path,
    *,
    relpath: str,
    corpus: str,
    authored_prompt: str,
    label: str,
    cfg: "Config",
    align: bool,
    live_review: bool,
    review_model: str,
    review_fn: Callable[..., ImageReviewResult] | None,
    ocr_fn: Callable[[Path], str | None] | None,
) -> list[str]:
    if not align or not corpus.strip():
        return []
    issues: list[str] = []
    scanned = (ocr_fn or ocr_image_text)(path)
    if scanned:
        issues.extend(
            image_ocr_alignment_violations(
                scanned, corpus_text=corpus, relpath=relpath
            )
        )
    if live_review:
        if review_fn is not None:
            verdict = review_fn(
                path, corpus_text=corpus, authored_prompt=authored_prompt, label=label
            )
        else:
            verdict = review_image_against_docs(
                path,
                corpus_text=corpus,
                authored_prompt=authored_prompt,
                label=label,
                cfg=cfg,
                model=review_model,
            )
        if not verdict.passed:
            issues.append(f"{relpath}: vision review FAIL — {verdict.reason}")
    return issues


def spec_files_for_bundle(cfg: "Config") -> list[Path]:
    """All committed ``animations/specs/*.scene.yaml`` files, sorted."""
    specs_dir = cfg.animations_dir / "specs"
    if not specs_dir.is_dir():
        return []
    return sorted(specs_dir.glob("*.scene.yaml"))


def generate_missing_images_for_bundle(
    cfg: "Config",
    *,
    image_fn: Callable[[str], bytes] | None = None,
    review_fn: Callable[..., ImageReviewResult] | None = None,
    ocr_fn: Callable[[Path], str | None] | None = None,
) -> list[str]:
    """Generate only **missing** image assets across all bundle specs.

    Used by ``docgen generate-all`` before the Manim stage so image scenes
    always have their assets on disk. Returns human-readable changelog lines.
    """
    msgs: list[str] = []
    for spec_path in spec_files_for_bundle(cfg):
        for res in generate_images_for_spec(
            cfg, spec_path, image_fn=image_fn, review_fn=review_fn, ocr_fn=ocr_fn
        ):
            if res.status == "generated":
                msgs.append(f"{spec_path.name}: generated {res.relpath}")
    return msgs
