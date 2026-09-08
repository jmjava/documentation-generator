"""Generate narration ``.md`` from repository sources using chat completions (OpenAI or Grok).

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


def merged_narration_from_source_settings(cfg: "Config", seg_id: str) -> NarrationFromSourceSettings:
    """Merge ``narration_from_source`` defaults with optional ``segments.<seg_id>`` overrides.

    ``hints`` are always **authored in YAML by the project owner** (never returned from OpenAI).
    """
    from docgen.config import (
        context_path_globs,
        optional_yaml_number,
        require_optional_yaml_string,
        require_yaml_string,
        string_list_block,
    )

    root = cfg.raw.get("narration_from_source")
    if not isinstance(root, dict):
        root = {}
    seg_block = root.get("segments")
    seg: dict[str, Any] = {}
    if isinstance(seg_block, dict):
        raw_seg = seg_block.get(seg_id)
        if isinstance(raw_seg, dict):
            seg = raw_seg

    paths, globs = context_path_globs(root, prefix="narration_from_source")
    extra_paths, extra_globs = context_path_globs(
        seg, prefix=f"narration_from_source.segments.{seg_id}"
    )
    paths = paths + extra_paths
    globs = globs + extra_globs

    hints = string_list_block(root, "hints", label="narration_from_source.hints")
    hints = hints + string_list_block(
        seg, "hints", label=f"narration_from_source.segments.{seg_id}.hints"
    )

    raw_model = root.get("model")
    model = (
        DEFAULT_MODEL
        if raw_model is None
        else require_yaml_string(
            raw_model, label="narration_from_source.model", source="docgen.yaml"
        )
    )
    temperature = optional_yaml_number(
        root,
        "temperature",
        default=DEFAULT_TEMPERATURE,
        label="narration_from_source.temperature",
    )
    max_bytes = int(
        optional_yaml_number(
            root,
            "max_context_bytes",
            default=DEFAULT_MAX_CONTEXT_BYTES,
            label="narration_from_source.max_context_bytes",
        )
    )

    raw_sys = root.get("system_prompt")
    require_optional_yaml_string(
        raw_sys, label="narration_from_source.system_prompt", source="docgen.yaml"
    )
    seg_sys_raw = seg.get("system_prompt")
    require_optional_yaml_string(
        seg_sys_raw,
        label=f"narration_from_source.segments.{seg_id}.system_prompt",
        source="docgen.yaml",
    )
    sys_override = raw_sys.strip() if isinstance(raw_sys, str) else ""
    seg_sys = seg_sys_raw.strip() if isinstance(seg_sys_raw, str) else ""
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
    missing: list[str] = []
    for rel in settings.context_paths + list(extra_paths):
        rel_s = str(rel).strip()
        if not rel_s:
            continue
        ap = _resolve_repo_path(repo_root, rel_s)
        if ap:
            paths.append(ap)
        else:
            missing.append(rel_s)
    if missing:
        raise ValueError(
            "declared context path(s) not found under repo_root: " + ", ".join(missing)
        )
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
        except OSError as exc:
            raise ValueError(f"cannot read context file {ap}: {exc}") from exc
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


def _existing_narration_text(cfg: "Config", seg_id: str) -> str:
    """Return current ``narration/<stem>.md`` text, or empty if missing."""
    seg_name = cfg.resolve_segment_name(seg_id)
    path = cfg.narration_dir / f"{seg_name}.md"
    if not path.is_file():
        # Match wizard asset discovery for NN-*.md fallbacks.
        if cfg.narration_dir.is_dir():
            for cand in cfg.narration_dir.glob(f"{seg_id}-*.md"):
                return cand.read_text(encoding="utf-8")
            for cand in cfg.narration_dir.glob(f"{seg_id}*.md"):
                return cand.read_text(encoding="utf-8")
        return ""
    return path.read_text(encoding="utf-8")


def generate_narration_markdown(
    cfg: "Config",
    seg_id: str,
    *,
    extra_paths: list[str],
    extra_hints: list[str],
    revision_notes: str = "",
    mode: str = "generate",
) -> str:
    """Call the chat model and return markdown body (does not write files).

    Owner hints from YAML and ``extra_hints`` from the caller are sent as guidance only;
    the returned markdown is model-generated.

    ``mode="revise"`` edits the existing narration file in place using
    ``revision_notes`` (requires both an on-disk script and non-empty notes).
    """
    from docgen.wizard import generate_narration_via_llm

    mode_norm = str(mode or "generate").strip().lower()
    if mode_norm not in ("generate", "revise"):
        raise ValueError(f"mode must be 'generate' or 'revise', not {mode!r}")
    notes = (revision_notes or "").strip()

    settings = merged_narration_from_source_settings(cfg, seg_id)
    snippets = collect_source_snippets(cfg, settings, extra_paths=extra_paths)
    # Revise can proceed with empty sources (current script + notes are enough);
    # full generate still requires context files.
    if not snippets and mode_norm != "revise":
        raise ValueError(
            "No source files collected. Add narration_from_source.context.paths/globs "
            "to docgen.yaml or pass extra paths on the CLI."
        )
    source_texts = [f"FILE: {label}\n```\n{body}\n```" for label, body in snippets]
    guidance = build_owner_hints_guidance(settings, extra_hints)
    seg_name = cfg.resolve_segment_name(seg_id)
    topic = cfg.narration_topic_label(seg_id)
    current = ""
    if mode_norm == "revise":
        current = _existing_narration_text(cfg, seg_id)
        if not current.strip():
            raise ValueError(
                f"no existing narration for segment {seg_id!r} to revise — "
                "run a full generate first, or drop --revise"
            )
        if not notes:
            raise ValueError("--revise requires --revision-notes")
    return generate_narration_via_llm(
        source_texts=source_texts,
        guidance=guidance,
        system_prompt=settings.system_prompt,
        model=settings.model,
        segment_name=seg_name,
        revision_notes=notes,
        temperature=settings.temperature,
        topic_label=topic,
        current_narration=current,
        mode=mode_norm,
        cfg=cfg,
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
