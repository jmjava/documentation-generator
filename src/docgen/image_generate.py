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
``<bundle>/<image path>``. ``docgen manim`` then loads the asset via the
``_image`` helper in ``scenes.py``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from docgen.openai_retry import call_with_rate_limit_retries
from docgen.scene_spec import iter_image_elements, load_scene_spec

if TYPE_CHECKING:
    from docgen.config import Config

DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1536x1024"


class ImageGenerationError(RuntimeError):
    """Raised when an image asset cannot be produced (bad path, no prompt, API failure)."""


@dataclass(frozen=True)
class ImageAssetResult:
    relpath: str
    path: Path
    status: str  # "generated" | "exists" | "dry-run"
    prompt: str


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
        return base64.b64decode(b64)
    url = getattr(data, "url", None) if data is not None else None
    if url:
        try:
            return fetch_url_bytes(str(url))
        except Exception as exc:
            raise ImageGenerationError(
                f"Image model {resolved!r} returned a URL but download failed: {exc}."
            ) from exc
    raise ImageGenerationError(
        f"Image response for model {resolved!r} had neither b64_json nor url; "
        "cannot write the asset."
    )


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

    results: list[ImageAssetResult] = []
    for el in elements:
        rel = str(el["image"]).strip()
        prompt = str(el.get("prompt") or "").strip()
        out = _resolve_asset_path(cfg, rel)

        if out.is_file() and not force:
            results.append(ImageAssetResult(rel, out, "exists", prompt))
            continue
        if not prompt:
            raise ImageGenerationError(
                f"{spec_path}: image element {rel!r} has no `prompt` and the asset is missing "
                f"({out}); add the file to the bundle or set a prompt in the spec."
            )
        if dry_run:
            results.append(ImageAssetResult(rel, out, "dry-run", prompt))
            continue

        fn = image_fn or (
            lambda p: generate_image_bytes(
                prompt=p, model=model, size=size, quality=quality, cfg=cfg
            )
        )
        data = fn(prompt)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        results.append(ImageAssetResult(rel, out, "generated", prompt))
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
