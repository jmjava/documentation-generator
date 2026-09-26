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
``image_prompt_alignment``). ``docgen manim`` then loads the asset via the
``_image`` helper in ``scenes.py``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from docgen.openai_retry import call_with_rate_limit_retries
from docgen.scene_spec import (
    image_prompt_alignment_violations,
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


def collect_alignment_corpus(cfg: "Config", spec: dict[str, Any]) -> str:
    """Narration + scene-generation hints + source snippets for one spec."""
    parts: list[str] = []
    seg_id = str(spec.get("segment_id") or "").strip()
    if seg_id:
        found = cfg.find_segment_asset(cfg.narration_dir, seg_id, ".md")
        if found is not None and found.is_file():
            try:
                parts.append(found.read_text(encoding="utf-8"))
            except OSError:
                pass
        from docgen.manim_scene_support import (
            collect_source_snippets,
            merged_scene_generation_settings,
        )

        settings = merged_scene_generation_settings(cfg, seg_id)
        for h in settings.hints:
            if str(h).strip():
                parts.append(str(h).strip())
        for label, text in collect_source_snippets(cfg, settings, extra_paths=[]):
            body = str(text or "").strip()
            if body:
                parts.append(f"{label}\n{body}")
    return "\n\n".join(p for p in parts if str(p).strip())


def _resolve_asset_path(cfg: "Config", relpath: str) -> Path:
    p = Path(relpath)
    if p.is_absolute() or ".." in p.parts:
        raise ImageGenerationError(
            f"image path {relpath!r} must be relative to the bundle directory "
            "(no absolute paths or '..')"
        )
    return cfg.base_dir / p


def generate_images_for_spec(
    cfg: "Config",
    spec_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    model_override: str | None = None,
    size_override: str | None = None,
    image_fn: Callable[[str], bytes] | None = None,
) -> list[ImageAssetResult]:
    """Generate missing image assets referenced by one ``*.scene.yaml``.

    Existing assets are kept unless ``force``. An image element whose asset is
    missing **and** has no ``prompt`` fails loud — either commit the file or
    give the toolchain a prompt to generate it from.

    ``image_fn`` is an injection point for tests (prompt → PNG bytes).
    """
    spec = load_scene_spec(spec_path)
    elements = iter_image_elements(spec)
    icfg = cfg.image_generation_config
    model = (model_override or "").strip() or str(icfg.get("model") or DEFAULT_IMAGE_MODEL)
    size = (size_override or "").strip() or str(icfg.get("size") or DEFAULT_IMAGE_SIZE)
    quality = icfg.get("quality")
    quality = str(quality).strip() if quality else None
    align = bool(icfg.get("align_with_docs", True))
    style = str(icfg.get("style") or "").strip() or DEFAULT_IMAGE_STYLE
    corpus = collect_alignment_corpus(cfg, spec) if align else ""

    if align:
        issues = image_prompt_alignment_violations(spec, corpus_text=corpus)
        if issues:
            joined = "\n  ".join(issues)
            raise ImageGenerationError(
                f"{spec_path}: image prompt alignment failed — rewrite each "
                f"`prompt` so it uses documented terms from narration/source "
                f"(or set image_generation.align_with_docs: false):\n  {joined}"
            )

    results: list[ImageAssetResult] = []
    for el in elements:
        rel = str(el["image"]).strip()
        prompt = str(el.get("prompt") or "").strip()
        out = _resolve_asset_path(cfg, rel)
        label = str(el.get("label") or "").strip()
        effective = (
            build_aligned_image_prompt(
                prompt, corpus_text=corpus, label=label, style=style
            )
            if align and prompt
            else prompt
        )

        if out.is_file() and not force:
            results.append(ImageAssetResult(rel, out, "exists", prompt, effective))
            continue
        if not prompt:
            raise ImageGenerationError(
                f"{spec_path}: image element {rel!r} has no `prompt` and the asset is missing "
                f"({out}); add the file to the bundle or set a prompt in the spec."
            )
        if dry_run:
            results.append(ImageAssetResult(rel, out, "dry-run", prompt, effective))
            continue

        fn = image_fn or (
            lambda p: generate_image_bytes(
                prompt=p, model=model, size=size, quality=quality, cfg=cfg
            )
        )
        data = fn(effective)
        if not data:
            raise ImageGenerationError(
                f"{spec_path}: image element {rel!r} — provider returned empty bytes"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        results.append(ImageAssetResult(rel, out, "generated", prompt, effective))
    return results


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
) -> list[str]:
    """Generate only **missing** image assets across all bundle specs.

    Used by ``docgen generate-all`` before the Manim stage so image scenes
    always have their assets on disk. Returns human-readable changelog lines.
    """
    msgs: list[str] = []
    for spec_path in spec_files_for_bundle(cfg):
        for res in generate_images_for_spec(cfg, spec_path, image_fn=image_fn):
            if res.status == "generated":
                msgs.append(f"{spec_path.name}: generated {res.relpath}")
    return msgs
