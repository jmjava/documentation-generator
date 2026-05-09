"""Generate narration ``.md`` from repository sources using OpenAI chat completions.

The **project owner** defines optional **hints** (plain strings) in ``docgen.yaml`` under
``narration_from_source.hints`` and/or per-segment ``narration_from_source.segments.<id>.hints``.
Those hints are **not** produced by OpenAI — they are written by the maintainer so the
model knows audience, tone, product names, compliance notes, etc. When hints are present
they are passed into the chat as **guidance**; OpenAI's job is only to **author the
narrative markdown** that will later feed ``docgen tts``.

Also configure ``context.paths`` / ``context.globs`` (repo-root-relative) so the model
sees real source files from the embedding project.

Output is written to the configured ``narration/`` directory for use by ``docgen tts``.
Plain paragraphs work best (``#`` headings are skipped by TTS; see ``tts.markdown_to_tts_plain``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config

DEFAULT_SYSTEM_PROMPT = """You write narration markdown for technical demo videos. The text will later be read by text-to-speech.

Rules:
- Use short paragraphs separated by blank lines.
- Do not use # headings (they are stripped and not spoken).
- Prefer flowing prose over bullet lists.
- Do not wrap stage directions in asterisks or parentheses on their own lines.
- Do not mention episode numbers, ordinal parts, or meta phrases like "this segment", "the next segment", "in this section", or "moving on to the next part" — describe the product and actions directly.
- Do not mention internal filenames, numeric prefixes, or authoring pipeline jargon unless it appears as a real user-facing term in the source documentation.
- Output only the narration body: no YAML front matter, no title line like "Here is the script", no code fences around the whole script."""

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.65
DEFAULT_MAX_CONTEXT_BYTES = 120_000


@dataclass(frozen=True)
class NarrationFromSourceSettings:
    model: str
    temperature: float
    max_context_bytes: int
    system_prompt: str
    hints: list[str]  # project-owner strings only; fed to the model as guidance
    context_paths: list[str]
    context_globs: list[str]


def _as_str_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, str):
        return [x] if x.strip() else []
    if isinstance(x, list):
        return [str(i).strip() for i in x if str(i).strip()]
    return []


def merged_narration_from_source_settings(cfg: "Config", seg_id: str) -> NarrationFromSourceSettings:
    """Merge ``narration_from_source`` defaults with optional ``segments.<seg_id>`` overrides.

    ``hints`` are always **authored in YAML by the project owner** (never returned from OpenAI).
    """
    root = cfg.raw.get("narration_from_source")
    if not isinstance(root, dict):
        root = {}
    seg_block = root.get("segments")
    seg: dict[str, Any] = {}
    if isinstance(seg_block, dict):
        raw_seg = seg_block.get(seg_id)
        if isinstance(raw_seg, dict):
            seg = raw_seg

    ctx_root = root.get("context")
    ctx_seg = seg.get("context")
    paths = _as_str_list((ctx_root or {}).get("paths") if isinstance(ctx_root, dict) else None)
    globs = _as_str_list((ctx_root or {}).get("globs") if isinstance(ctx_root, dict) else None)
    if isinstance(ctx_seg, dict):
        paths = paths + _as_str_list(ctx_seg.get("paths"))
        globs = globs + _as_str_list(ctx_seg.get("globs"))

    hints = _as_str_list(root.get("hints")) + _as_str_list(seg.get("hints"))

    model = str(root.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    temperature = float(root.get("temperature", DEFAULT_TEMPERATURE))
    max_bytes = int(root.get("max_context_bytes", DEFAULT_MAX_CONTEXT_BYTES))

    sys_override = str(root.get("system_prompt", "")).strip()
    seg_sys = str(seg.get("system_prompt", "")).strip()
    if seg_sys:
        system_prompt = seg_sys
    elif sys_override:
        system_prompt = sys_override
    else:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    return NarrationFromSourceSettings(
        model=model,
        temperature=temperature,
        max_context_bytes=max_bytes,
        system_prompt=system_prompt,
        hints=hints,
        context_paths=paths,
        context_globs=globs,
    )


def _resolve_repo_path(repo_root: Path, rel: str) -> Path | None:
    p = Path(rel)
    ap = (p if p.is_absolute() else (repo_root / p)).resolve()
    try:
        ap.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return ap if ap.is_file() else None


def _collect_paths_from_globs(repo_root: Path, patterns: list[str]) -> list[Path]:
    found: set[Path] = set()
    rr = repo_root.resolve()
    for pat in patterns:
        pat = pat.strip()
        if not pat:
            continue
        # pathlib supports ** from Python 3.5+ with recursive glob
        for p in rr.glob(pat):
            if p.is_file():
                try:
                    p.resolve().relative_to(rr)
                except ValueError:
                    continue
                found.add(p.resolve())
    return sorted(found)


def collect_source_snippets(
    cfg: "Config",
    settings: NarrationFromSourceSettings,
    *,
    extra_paths: list[str],
    max_context_bytes: int | None = None,
) -> list[tuple[str, str]]:
    """Return ``(label, text)`` pairs for the LLM user message, capped by total bytes."""
    limit = max_context_bytes if max_context_bytes is not None else settings.max_context_bytes
    repo_root = cfg.repo_root.resolve()
    paths: list[Path] = []
    for rel in settings.context_paths + list(extra_paths):
        ap = _resolve_repo_path(repo_root, rel)
        if ap:
            paths.append(ap)
    paths.extend(_collect_paths_from_globs(repo_root, settings.context_globs))
    # de-dupe preserve order
    seen: set[Path] = set()
    ordered: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            ordered.append(rp)

    snippets: list[tuple[str, str]] = []
    total = 0
    per_file_cap = max(8_192, limit // max(1, len(ordered)) if ordered else limit)

    for ap in ordered:
        try:
            text = ap.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel_label = str(ap.relative_to(repo_root))
        if len(text) > per_file_cap:
            text = text[:per_file_cap] + "\n\n… [truncated for context budget]\n"
        if total + len(text) > limit:
            remain = limit - total
            if remain <= 100:
                break
            text = text[:remain] + "\n… [truncated]\n"
        snippets.append((rel_label, text))
        total += len(text)
        if total >= limit:
            break
    return snippets


def build_owner_hints_guidance(
    settings: NarrationFromSourceSettings, extra_hints: list[str]
) -> str:
    """Format **project-owner** hints for the LLM user message (guidance section).

    ``extra_hints`` come from the CLI (also owner-supplied), never from the model.
    """
    lines = list(settings.hints) + list(extra_hints)
    if not lines:
        return ""
    return "\n".join(f"- {h}" for h in lines if h.strip())


def generate_narration_markdown(
    cfg: "Config",
    seg_id: str,
    *,
    extra_paths: list[str],
    extra_hints: list[str],
) -> str:
    """Call OpenAI and return markdown body (does not write files).

    Owner hints from YAML and ``extra_hints`` from the caller are sent as guidance only;
    the returned markdown is model-generated.
    """
    from docgen.wizard import generate_narration_via_llm

    settings = merged_narration_from_source_settings(cfg, seg_id)
    snippets = collect_source_snippets(cfg, settings, extra_paths=extra_paths)
    if not snippets:
        raise ValueError(
            "No source files collected. Add narration_from_source.context.paths/globs "
            "to docgen.yaml or pass extra paths on the CLI."
        )
    source_texts = [f"FILE: {label}\n```\n{body}\n```" for label, body in snippets]
    guidance = build_owner_hints_guidance(settings, extra_hints)
    seg_name = cfg.resolve_segment_name(seg_id)
    topic = cfg.narration_topic_label(seg_id)
    return generate_narration_via_llm(
        source_texts=source_texts,
        guidance=guidance,
        system_prompt=settings.system_prompt,
        model=settings.model,
        segment_name=seg_name,
        revision_notes="",
        temperature=settings.temperature,
        topic_label=topic,
    )


def write_narration_markdown(
    cfg: "Config",
    seg_id: str,
    body: str,
    *,
    force: bool = False,
) -> Path:
    """Write ``body`` to ``narration/<segment_name>.md``."""
    seg_name = cfg.resolve_segment_name(seg_id)
    out_dir = cfg.narration_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{seg_name}.md"
    if out.exists() and not force:
        raise FileExistsError(str(out))
    out.write_text(body.strip() + "\n", encoding="utf-8")
    return out
