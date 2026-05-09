"""LLM-driven **scene spec YAML** for ``docgen scene-spec-generate``.

The model emits only structured YAML validated by :mod:`docgen.scene_spec`, then
``docgen scene-compile`` (or ``--compile``) turns it into layout-safe Manim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from docgen.openai_retry import call_with_rate_limit_retries
from docgen.scene_generate import (
    SceneGenerationError,
    collect_source_snippets,
    derive_class_name,
    extract_reference_classes,
    merged_scene_generation_settings,
)
from docgen.scene_generate import _load_narration as load_narration_for_scene
from docgen.scene_generate import _load_timing_segments as load_timing_for_scene
from docgen.scene_spec import (
    ALLOWED_COLORS,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SceneSpecError,
    align_wait_at_to_words,
    auto_paginate,
    compile_scene_class,
    layout_budget_violations,
    layout_stack_budget,
    validate_scene_spec,
)

if TYPE_CHECKING:
    from docgen.config import Config

DEFAULT_SCENE_SPEC_TEMPERATURE = 0.35

_SCENE_SPEC_SYSTEM_BASE = f"""You author **declarative Manim scene specs** as a single YAML document (not Python).

**Planning / lookahead (mandatory before you write YAML):**
1. List every **page** and how many **rows** it will have. The toolchain does **not** auto-scale stacks.
2. For **each page** separately, compute: (a) **vertical stack height** = sum over rows of ``max(box heights in that row)`` plus ``(n_rows - 1) * row_gap``; (b) **widest row width** = sum of box widths in that row plus ``(n_boxes - 1) * column_gap`` for multi-box rows.
3. Compare to the **frame budget** in the user message (depends on ``title.font_size`` and ``first_row_title_buff``). If vertical stack exceeds budget **or** any row is wider than the safe width, **redesign**: add ``pages``, reduce ``height`` (often 0.72–0.9 for busy pages), tighten ``row_gap``, split wide rows, or shorten labels — then recompute until every page passes.
4. Only after all pages pass the mental math, output the YAML.

Output discipline:
- Output **only** one YAML document. You may wrap it in a ```yaml fenced block.
- Do **not** include timing_key (the toolchain merges it from docgen.yaml).
- Do **not** add commentary outside the YAML.
- All string **labels** must be short ASCII phrases (no unicode arrows, smart quotes, or em-dash — use "->" or "-" in labels if needed).
- **Concrete numeric types** in YAML: run_time, width, height, font_size must be numbers, not quoted strings.

Required keys:
- segment_id: string (echo the value from the user message exactly)
- class_name: string (echo the value from the user message exactly)
- title: mapping with text (string), font_size (int, >= 14), color (one of the palette tokens below)
- **Exactly one of:** ``rows`` (non-empty list of row mappings, single page) **or** ``pages`` (non-empty list of page mappings; each page has ``rows`` as above, optionally ``transition``: fade | none for pages after the first)

Each row must have:
- run_time: positive number (seconds for timed_play FadeIn of that row)
- boxes: non-empty list of box mappings, each with:
  - label: string
  - color: one of the palette tokens
  - width: positive number (typical 2.0–6.0; safe row total ≤ ~13 wide at dogfood resolution)
  - height: positive number (typical 0.65–1.1; **smaller when a page has many rows**)
  - font_size: int >= 14

Optional per-row (at most one of):
- wait_segment: non-negative int — wait_until that Whisper segment's **start** (often too early if the label word is spoken mid-segment).
- wait_at: non-negative number — absolute seconds into the narration audio; use word timings in timing.json when labels must appear on first mention.

Optional top-level:
- layout: optional first_row_title_buff, row_gap, column_gap (positive numbers);
  for multi-page specs also page_transition: fade | none (default fade), page_transition_run_time (default 0.45, max 5).

Use either **rows** (single page) OR **pages** (list of {{ rows: [...], transition?: fade|none }} — transition on pages after the first overrides layout.page_transition for exiting the previous page; first page has no transition in).

Palette tokens (exact spelling): {", ".join(sorted(ALLOWED_COLORS))}

Design goals:
- **Frame:** dogfood Manim canvas is ~14.22 × 8 units; title + buffer eat the top — see user-message budget. Never stack so many tall rows that boxes would clip off the bottom.
- **Do not** rely on shrinking: split into **pages** with fade between them.
- **Rows** within a page stack vertically; multiple boxes in one row arrange horizontally with safe spacing.
- Mirror **narration beats**; prefer **wait_at** from word-level times when first mention is not at a segment boundary; otherwise wait_segment is acceptable.
- Keep labels concise; narration may be longer than on-screen text.
"""


def scene_spec_system_prompt(cfg: Config, seg_id: str) -> str:
    """Optional override: ``manim_scene_generation.scene_spec_system_prompt`` or per-segment."""
    root = cfg.raw.get("manim_scene_generation")
    if not isinstance(root, dict):
        return _SCENE_SPEC_SYSTEM_BASE
    seg_block = root.get("segments")
    seg: dict[str, Any] = {}
    if isinstance(seg_block, dict):
        raw_seg = seg_block.get(seg_id)
        if isinstance(raw_seg, dict):
            seg = raw_seg
    ovr = str(seg.get("scene_spec_system_prompt", "")).strip()
    if ovr:
        return ovr
    ovr_root = str(root.get("scene_spec_system_prompt", "")).strip()
    return ovr_root if ovr_root else _SCENE_SPEC_SYSTEM_BASE


_FENCE_YAML_RE = re.compile(
    r"```(?:yaml|yml)?\s*\n(?P<body>[\s\S]*?)\n```",
    re.IGNORECASE,
)


def strip_yaml_fences(text: str) -> str:
    text = text.strip()
    m = _FENCE_YAML_RE.search(text)
    if m:
        return m.group("body").strip()
    return text


def _invoke_llm(
    *, system_prompt: str, user_message: str, model: str, temperature: float
) -> str:
    from docgen.scene_generate import call_llm

    return call_with_rate_limit_retries(
        lambda: call_llm(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            temperature=temperature,
        )
    )


def build_scene_spec_user_message(
    *,
    seg_id: str,
    seg_name: str,
    class_name: str,
    narration_text: str,
    whisper_segments: list[dict],
    hints: list[str],
    extra_hints: list[str],
    reference_scenes: str,
    source_snippets: list[tuple[str, str]],
) -> str:
    """User message: echo ids + same context as scene-generate, demand YAML spec."""
    parts: list[str] = []
    parts.append(
        f"Produce a **scene spec YAML** (not Python) for segment `{seg_id}` / class `{class_name}` "
        f"(narration stem `{seg_name}`)."
    )
    parts.append("")
    parts.append("**Required YAML fields** — use these exact values:")
    parts.append(f"  segment_id: {json.dumps(str(seg_id).strip())}")
    parts.append(f"  class_name: {json.dumps(class_name)}")
    parts.append("")
    parts.append("--- NARRATION ---")
    parts.append(narration_text.strip() or "(empty)")
    parts.append("")
    parts.append(f"--- TIMING (`timing.json` key {seg_name!r}; wait_segment indices refer to this list) ---")
    if whisper_segments:
        compact = [
            {
                "i": i,
                "start": float(s.get("start", 0.0)),
                "end": float(s.get("end", 0.0)),
                "text": str(s.get("text", "")).strip(),
            }
            for i, s in enumerate(whisper_segments[:40])
        ]
        parts.append(json.dumps(compact, indent=2))
    else:
        parts.append("[]  # omit wait_segment on rows, or the compiler still works")

    all_hints = list(hints) + list(extra_hints)
    if all_hints:
        parts.append("")
        parts.append("--- PROJECT-OWNER HINTS ---")
        for h in all_hints:
            if str(h).strip():
                parts.append(f"- {str(h).strip()}")

    if reference_scenes:
        parts.append("")
        parts.append(
            "--- REFERENCE (existing Manim classes — steal **ideas**, output YAML only) ---"
        )
        parts.append(reference_scenes)

    parts.append("")
    parts.append("--- FRAME / LAYOUT BUDGET (plan every page; scene-spec-generate rejects overflow) ---")
    parts.append(
        f"Dogfood Manim frame ≈ {FRAME_WIDTH} × {FRAME_HEIGHT} Manim units. "
        "Per page vertical cost = sum over rows of max(box height in row) + (n_rows - 1) * row_gap. "
        "That total must stay at or below the budget implied by your title.font_size and layout.first_row_title_buff. "
        "Per row horizontal cost = sum(box widths) + (n_boxes - 1) * column_gap; keep ≤ ~13."
    )
    parts.append(
        f"Reference max stack heights: "
        f"title 36 + first_row_title_buff 0.5 → ≈ {layout_stack_budget({'font_size': 36}, {'first_row_title_buff': 0.5}):.2f} u; "
        f"title 32 + buff 0.45 → ≈ {layout_stack_budget({'font_size': 32}, {'first_row_title_buff': 0.45}):.2f} u. "
        "Recompute if you change those fields."
    )
    return "\n".join(parts)


@dataclass(frozen=True)
class SceneSpecGenerationResult:
    seg_id: str
    seg_name: str
    class_name: str
    spec: dict[str, Any]
    yaml_text: str
    prompt: str
    raw_response: str


def normalize_spec_from_llm(
    data: dict[str, Any],
    *,
    seg_id: str,
    class_name: str,
) -> dict[str, Any]:
    """Force segment/class from CLI; strip timing_key for on-disk specs."""
    out = dict(data)
    out["segment_id"] = str(seg_id).strip()
    out["class_name"] = class_name
    out.pop("timing_key", None)
    return out


def spec_to_yaml_text(spec: dict[str, Any]) -> str:
    return yaml.dump(
        spec,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=120,
    ).rstrip() + "\n"


def _load_timing_words(cfg: Config, timing_key: str) -> list[dict[str, Any]]:
    """Return the ``words`` list from ``animations/timing.json`` for ``timing_key`` (best effort)."""
    timing_path = cfg.animations_dir / "timing.json"
    if not timing_path.exists():
        return []
    try:
        data = json.loads(timing_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    block = data.get(timing_key) or {}
    words = block.get("words") if isinstance(block, dict) else None
    return list(words) if isinstance(words, list) else []


def linted_class_block_from_spec(
    cfg: Config,
    spec: dict[str, Any],
    *,
    timing_key: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Merge ``timing_key``, auto-paginate + word-align, compile, run ``manim_scene_lint``."""
    from docgen.scene_generate import SceneGenerationError, lint_generated_block

    merged = dict(spec)
    sid = str(merged["segment_id"]).strip()
    if timing_key is not None:
        merged["timing_key"] = timing_key
    elif not merged.get("timing_key"):
        merged["timing_key"] = cfg.resolve_segment_name(sid)

    # Engine-side layout planning + audio sync so authored YAML stays minimal.
    merged = auto_paginate(merged)
    words = _load_timing_words(cfg, str(merged["timing_key"]))
    if words:
        merged = align_wait_at_to_words(merged, words)

    try:
        class_block = compile_scene_class(merged)
    except SceneSpecError as exc:
        raise SceneGenerationError(str(exc)) from exc
    issues = lint_generated_block(
        class_block,
        min_font_size=cfg.manim_min_font_size,
        unsafe_unicode=cfg.manim_unsafe_unicode,
    )
    if issues:
        joined = "\n  ".join(issues[:20])
        raise SceneGenerationError(
            f"compiled scene failed manim_scene_lint:\n  {joined}"
        )
    return class_block, merged


def inject_class_block_into_scenes_py(
    cfg: Config,
    *,
    seg_id: str,
    class_name: str,
    class_block: str,
) -> Path:
    from docgen.scene_generate import SceneGenerationError, ensure_scenes_bootstrap, inject_or_replace

    scenes_path = cfg.animations_dir / "scenes.py"
    try:
        ensure_scenes_bootstrap(scenes_path)
    except SceneGenerationError as exc:
        raise SceneGenerationError(str(exc)) from exc
    text = scenes_path.read_text(encoding="utf-8")
    new_text = inject_or_replace(text, str(seg_id).strip(), class_name, class_block)
    scenes_path.write_text(new_text, encoding="utf-8")
    return scenes_path


def _save_draft(cfg: Config, seg_id: str, content: str) -> Path:
    drafts = cfg.animations_dir / ".scene-spec-drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    path = drafts / f"{seg_id}.draft.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def generate_scene_spec(
    cfg: Config,
    seg_id: str,
    *,
    extra_paths: list[str],
    extra_hints: list[str],
    class_name_override: str | None = None,
    dry_run: bool = False,
    model_override: str | None = None,
    temperature_override: float | None = None,
    llm: Callable[..., str] | None = None,
) -> SceneSpecGenerationResult:
    """Prompt OpenAI for YAML, validate schema, compile+lint the merged Python."""
    settings = merged_scene_generation_settings(cfg, seg_id)
    seg_name = cfg.resolve_segment_name(seg_id)
    class_name = derive_class_name(
        seg_id, seg_name, class_name_override or settings.class_name
    )
    narration_text = load_narration_for_scene(cfg, seg_id, seg_name)
    whisper_segments = load_timing_for_scene(cfg, seg_name)

    scenes_path = cfg.animations_dir / "scenes.py"
    existing = scenes_path.read_text(encoding="utf-8") if scenes_path.exists() else ""
    reference_scenes = extract_reference_classes(existing)
    snippets = collect_source_snippets(cfg, settings, extra_paths=extra_paths)

    system_prompt = scene_spec_system_prompt(cfg, seg_id)
    user_message = build_scene_spec_user_message(
        seg_id=seg_id,
        seg_name=seg_name,
        class_name=class_name,
        narration_text=narration_text,
        whisper_segments=whisper_segments,
        hints=settings.hints,
        extra_hints=extra_hints,
        reference_scenes=reference_scenes,
        source_snippets=snippets,
    )

    if dry_run:
        return SceneSpecGenerationResult(
            seg_id=seg_id,
            seg_name=seg_name,
            class_name=class_name,
            spec={},
            yaml_text="",
            prompt=f"--- system ---\n{system_prompt}\n\n--- user ---\n{user_message}",
            raw_response="",
        )

    model = (model_override or "").strip() or settings.model
    temperature = (
        float(temperature_override)
        if temperature_override is not None
        else float(settings.temperature or DEFAULT_SCENE_SPEC_TEMPERATURE)
    )
    invoke = llm or _invoke_llm
    raw = invoke(
        system_prompt=system_prompt,
        user_message=user_message,
        model=model,
        temperature=temperature,
    )
    body = strip_yaml_fences(raw)
    try:
        loaded = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        draft = _save_draft(cfg, seg_id, raw)
        raise SceneGenerationError(
            f"segment {seg_id}: LLM output is not valid YAML ({exc}). Draft: {draft}"
        ) from exc
    if not isinstance(loaded, dict):
        draft = _save_draft(cfg, seg_id, raw)
        raise SceneGenerationError(
            f"segment {seg_id}: LLM YAML root must be a mapping. Draft: {draft}"
        )

    merged_spec = normalize_spec_from_llm(loaded, seg_id=seg_id, class_name=class_name)
    try:
        validate_scene_spec(merged_spec, path_label=f"segment {seg_id}")
    except SceneSpecError as exc:
        draft = _save_draft(cfg, seg_id, body)
        raise SceneGenerationError(
            f"segment {seg_id}: scene spec invalid: {exc}. Draft: {draft}"
        ) from exc

    budget_issues = layout_budget_violations(merged_spec)
    if budget_issues:
        draft = _save_draft(cfg, seg_id, body)
        joined = "\n  ".join(budget_issues)
        raise SceneGenerationError(
            f"segment {seg_id}: scene spec exceeds frame budget:\n  {joined}\nDraft: {draft}"
        )

    try:
        _, _ = linted_class_block_from_spec(cfg, merged_spec, timing_key=seg_name)
    except SceneGenerationError as exc:
        draft = _save_draft(cfg, seg_id, body)
        # linted_class_block_from_spec message already describes failure
        raise SceneGenerationError(f"{exc} Draft: {draft}") from exc

    yaml_text = spec_to_yaml_text(merged_spec)
    return SceneSpecGenerationResult(
        seg_id=seg_id,
        seg_name=seg_name,
        class_name=class_name,
        spec=merged_spec,
        yaml_text=yaml_text,
        prompt=user_message,
        raw_response=raw,
    )
