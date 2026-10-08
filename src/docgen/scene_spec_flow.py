"""Scene-spec generate steps kept out of the hotspot module's complex functions.

``scene_spec_generate`` re-exports the public entry points. Each function here
stays at or under the complexity gate (CCN 10, NLOC 80).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from docgen.config import Config

import yaml

from docgen.manim_scene_support import (
    SceneGenerationError,
    collect_source_snippets,
    derive_class_name,
    extract_reference_classes,
    merged_scene_generation_settings,
)
from docgen.manim_scene_support import _load_narration as load_narration_for_scene
from docgen.manim_scene_support import _load_timing_segments as load_timing_for_scene
from docgen.scene_spec import (
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SceneSpecError,
    auto_fit_row_widths,
    auto_paginate,
    cluster_subject_beats,
    coerce_legacy_wait_at_to_whisper_rows,
    compile_scene_class,
    layout_budget_violations,
    layout_density_violations,
    layout_stack_budget,
    narration_sentences,
    pacing_violations,
    sanitize_pacing_conflicts,
    spec_rows_reference_whisper_waits,
    sync_row_labels_to_whisper_words,
    upgrade_wait_segments_to_wait_words,
    validate_scene_spec,
)

def _beat_lines(narration_text: str, word_count: int) -> list[str]:
    beats = cluster_subject_beats(narration_sentences(narration_text))
    if not beats:
        return []
    wc_note = f" ({word_count} Whisper words)" if word_count > 0 else ""
    lines = [
        f"**SUBJECT BEATS{wc_note} — cover each with ≥1 spoken-phrase label "
        f"(hold the board inside a beat; change when the topic shifts):**"
    ]
    for i, beat in enumerate(beats, start=1):
        preview = beat if len(beat) <= 160 else beat[:157] + "..."
        lines.append(f"  {i}. {preview}")
    lines.append(
        "scene-spec-generate **rejects** specs that leave beats uncovered or use "
        "labels that are not spoken in the narration (not a blind label count)."
    )
    lines.append("")
    return lines


def _hint_lines(hints: list[str], extra_hints: list[str]) -> list[str]:
    all_hints = list(hints) + list(extra_hints)
    if not all_hints:
        return []
    lines = ["", "--- PROJECT-OWNER HINTS ---"]
    for hint in all_hints:
        if str(hint).strip():
            lines.append(f"- {str(hint).strip()}")
    return lines


def _source_doc_lines(source_snippets: list[tuple[str, str]]) -> list[str]:
    if not source_snippets:
        return []
    lines = [
        "",
        "--- SOURCE DOCUMENTATION ---",
        "Use these excerpts when authoring box labels **and** image prompts. "
        "Do not invent product names, APIs, or architecture that is not in this "
        "source or the narration.",
    ]
    for label, text in source_snippets:
        body = str(text or "").strip()
        if not body:
            continue
        lines.extend(["", f"### {label}", body])
    return lines


def _reference_lines(reference_scenes: str) -> list[str]:
    if not reference_scenes:
        return []
    return [
        "",
        "--- REFERENCE (existing Manim classes — steal **ideas**, output YAML only) ---",
        reference_scenes,
    ]


def _budget_lines() -> list[str]:
    horiz_safe = FRAME_WIDTH - 1.0
    budget_default = layout_stack_budget({"font_size": 36}, {"first_row_title_buff": 0.5})
    budget_compact = layout_stack_budget({"font_size": 32}, {"first_row_title_buff": 0.45})
    return [
        "",
        "--- FRAME / LAYOUT BUDGET (plan every page; scene-spec-generate rejects overflow) ---",
        (
            f"Frame ≈ {FRAME_WIDTH:.2f} × {FRAME_HEIGHT:.2f} Manim units. "
            f"Horizontal safe width ≈ {horiz_safe:.2f} u "
            "(sum of box widths + (n_boxes-1)*column_gap per row must stay ≤ this)."
        ),
        (
            "**Vertical stack budgets** (use these numbers unless you change "
            "title.font_size / layout.first_row_title_buff):\n"
            f"  • Default font_size=36, first_row_title_buff=0.5 → "
            f"max stack height ≈ {budget_default:.2f} u\n"
            f"  • Compact font_size=32, first_row_title_buff=0.45 → "
            f"max stack height ≈ {budget_compact:.2f} u\n"
            "Per page: sum(max box height per row) + (n_rows-1)*row_gap ≤ that budget. "
            "When you would exceed it, spill to another page (do not shrink/cram)."
        ),
    ]


def build_scene_spec_user_message(
    *,
    seg_id: str,
    seg_name: str,
    class_name: str,
    narration_text: str,
    timing_enrichment: str,
    hints: list[str],
    extra_hints: list[str],
    reference_scenes: str,
    source_snippets: list[tuple[str, str]],
    word_count: int = 0,
) -> str:
    """User message: narration + timing + hints; demand YAML spec."""
    parts = [
        (
            f"Produce a **scene spec YAML** (not Python) for segment `{seg_id}` / "
            f"class `{class_name}` (narration stem `{seg_name}`)."
        ),
        "",
        "**Required YAML fields** — use these exact values:",
        f"  segment_id: {json.dumps(str(seg_id).strip())}",
        f"  class_name: {json.dumps(class_name)}",
        "",
        "--- NARRATION ---",
        narration_text.strip() or "(empty)",
        "",
    ]
    parts.extend(_beat_lines(narration_text, word_count))
    parts.append(timing_enrichment.strip())
    parts.extend(_hint_lines(hints, extra_hints))
    parts.extend(_source_doc_lines(source_snippets))
    parts.extend(_reference_lines(reference_scenes))
    parts.extend(_budget_lines())
    return "\n".join(parts)


def _merge_timing_key(cfg: "Config", spec: dict[str, Any], timing_key: str | None) -> dict[str, Any]:
    merged = dict(spec)
    sid = str(merged["segment_id"]).strip()
    if timing_key is not None:
        merged["timing_key"] = timing_key
        return merged
    if not merged.get("timing_key"):
        merged["timing_key"] = cfg.resolve_segment_name(sid)
    return merged


def _sync_audio(
    merged: dict[str, Any],
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = coerce_legacy_wait_at_to_whisper_rows(merged, words, segments)
    if words and segments:
        merged = upgrade_wait_segments_to_wait_words(merged, words, segments)
    if words:
        merged = sync_row_labels_to_whisper_words(merged, words, overwrite=True)
    return merged


def _ensure_words_if_paced(merged: dict[str, Any], words: list, tk: str) -> None:
    if spec_rows_reference_whisper_waits(merged) and not words:
        raise SceneGenerationError(
            f"timing.json has no word-level `words` for stem {tk!r}; run `docgen timestamps` "
            "before compiling scenes that use wait_word or wait_segment."
        )


def _ensure_pacing(merged: dict[str, Any], words: list, tk: str) -> None:
    pace_issues = pacing_violations(merged, words_present=bool(words))
    if not pace_issues:
        return
    shown = "\n  ".join(pace_issues[:12])
    more = f"\n  (+{len(pace_issues) - 12} more)" if len(pace_issues) > 12 else ""
    raise SceneGenerationError(
        f"scene pacing failed for timing_key {tk!r} — every story box needs a "
        f"spoken label matched in timing.json words (or pace: none):\n  {shown}{more}"
    )


def _compile_and_lint(cfg: "Config", merged: dict[str, Any], words: list) -> str:
    from docgen.manim_scene_support import lint_generated_block

    try:
        class_block = compile_scene_class(merged, words=words or None)
    except SceneSpecError as exc:
        raise SceneGenerationError(str(exc)) from exc
    issues = lint_generated_block(
        class_block,
        min_font_size=cfg.manim_min_font_size,
        unsafe_unicode=cfg.manim_unsafe_unicode,
    )
    if issues:
        joined = "\n  ".join(issues[:20])
        raise SceneGenerationError(f"compiled scene failed manim_scene_lint:\n  {joined}")
    return class_block


def linted_class_block_from_spec(
    cfg: "Config",
    spec: dict[str, Any],
    *,
    timing_key: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Merge ``timing_key``, auto-paginate + word-align, compile, run ``manim_scene_lint``."""
    from docgen.scene_spec_generate import _load_timing_words

    merged = _merge_timing_key(cfg, spec, timing_key)
    merged = auto_paginate(auto_fit_row_widths(merged))
    tk = str(merged["timing_key"])
    segments = load_timing_for_scene(cfg, tk)
    words = _load_timing_words(cfg, tk)
    merged = _sync_audio(merged, words, segments)
    _ensure_words_if_paced(merged, words, tk)
    _ensure_pacing(merged, words, tk)
    return _compile_and_lint(cfg, merged, words), merged


def _load_yaml_mapping(cfg: "Config", seg_id: str, raw: str) -> tuple[str, dict[str, Any]]:
    from docgen.scene_spec_generate import _save_draft, strip_yaml_fences

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
    return body, loaded


def _reject_joined(
    cfg: "Config",
    seg_id: str,
    body: str,
    issues: list[str],
    headline: str,
) -> None:
    if not issues:
        return
    from docgen.scene_spec_generate import _save_draft

    draft = _save_draft(cfg, seg_id, body)
    joined = "\n  ".join(issues)
    raise SceneGenerationError(f"segment {seg_id}: {headline}:\n  {joined}\nDraft: {draft}")


def _ensure_schema(cfg: "Config", seg_id: str, body: str, merged: dict[str, Any]) -> None:
    from docgen.scene_spec_generate import _save_draft

    try:
        validate_scene_spec(merged, path_label=f"segment {seg_id}")
    except SceneSpecError as exc:
        draft = _save_draft(cfg, seg_id, body)
        raise SceneGenerationError(
            f"segment {seg_id}: scene spec invalid: {exc}. Draft: {draft}"
        ) from exc


def _ensure_density(
    cfg: "Config",
    *,
    seg_id: str,
    body: str,
    merged: dict[str, Any],
    narration_text: str,
    word_count: int,
    enforce_density: bool,
    density_slack: int,
) -> None:
    if not enforce_density:
        return
    if not getattr(cfg, "subject_beat_coverage_enabled", True):
        return
    issues = layout_density_violations(
        merged,
        narration_text=narration_text,
        word_count=word_count,
        slack=density_slack,
    )
    _reject_joined(cfg, seg_id, body, issues, "scene spec failed subject-beat coverage")


def _ensure_image_alignment(
    cfg: "Config",
    *,
    seg_id: str,
    body: str,
    merged: dict[str, Any],
    corpus_text: str,
    narration_text: str,
) -> None:
    from docgen.image_align import image_prompt_alignment_enabled, image_prompt_alignment_violations

    if not image_prompt_alignment_enabled(cfg):
        return
    issues = image_prompt_alignment_violations(
        merged, corpus_text=corpus_text or narration_text
    )
    _reject_joined(cfg, seg_id, body, issues, "image prompt alignment failed")


def _ensure_compiles(cfg: "Config", seg_id: str, body: str, merged: dict[str, Any], seg_name: str) -> None:
    from docgen.scene_spec_generate import _save_draft

    try:
        linted_class_block_from_spec(cfg, merged, timing_key=seg_name)
    except SceneGenerationError as exc:
        draft = _save_draft(cfg, seg_id, body)
        raise SceneGenerationError(f"{exc} Draft: {draft}") from exc


def _parse_and_harden_llm_spec(
    cfg: "Config",
    *,
    seg_id: str,
    class_name: str,
    seg_name: str,
    narration_text: str,
    word_count: int,
    raw: str,
    enforce_density: bool,
    density_slack: int = 0,
    corpus_text: str = "",
) -> dict[str, Any]:
    from docgen.scene_spec_generate import normalize_spec_from_llm

    body, loaded = _load_yaml_mapping(cfg, seg_id, raw)
    merged = sanitize_pacing_conflicts(auto_paginate(auto_fit_row_widths(
        normalize_spec_from_llm(loaded, seg_id=seg_id, class_name=class_name)
    )))
    _ensure_schema(cfg, seg_id, body, merged)
    _reject_joined(
        cfg, seg_id, body, layout_budget_violations(merged), "scene spec exceeds frame budget"
    )
    _ensure_density(
        cfg,
        seg_id=seg_id,
        body=body,
        merged=merged,
        narration_text=narration_text,
        word_count=word_count,
        enforce_density=enforce_density,
        density_slack=density_slack,
    )
    _ensure_image_alignment(
        cfg,
        seg_id=seg_id,
        body=body,
        merged=merged,
        corpus_text=corpus_text,
        narration_text=narration_text,
    )
    _ensure_compiles(cfg, seg_id, body, merged, seg_name)
    return merged


def _corpus_text(
    narration_text: str,
    hints: list[str],
    extra_hints: list[str],
    snippets: list[tuple[str, str]],
) -> str:
    parts = [narration_text]
    for hint in list(hints) + list(extra_hints):
        if str(hint).strip():
            parts.append(str(hint).strip())
    for label, text in snippets:
        body = str(text or "").strip()
        if body:
            parts.append(f"{label}\n{body}")
    return "\n\n".join(part for part in parts if str(part).strip())


def _prepare_generation(cfg: "Config", seg_id: str, extra_paths: list[str], extra_hints: list[str], class_name_override: str | None) -> dict[str, Any]:
    from docgen.manim_scene_support import build_timing_enrichment_for_prompt
    from docgen.scene_spec_generate import _load_timing_words, scene_spec_system_prompt

    settings = merged_scene_generation_settings(cfg, seg_id)
    seg_name = cfg.resolve_segment_name(seg_id)
    class_name = derive_class_name(seg_id, seg_name, class_name_override or settings.class_name)
    narration_text = load_narration_for_scene(cfg, seg_id, seg_name)
    whisper_segments = load_timing_for_scene(cfg, seg_name)
    timing_block = build_timing_enrichment_for_prompt(cfg, seg_id, seg_name, whisper_segments)
    word_count = len(_load_timing_words(cfg, seg_name))
    scenes_path = cfg.animations_dir / "scenes.py"
    existing = scenes_path.read_text(encoding="utf-8") if scenes_path.exists() else ""
    snippets = collect_source_snippets(cfg, settings, extra_paths=extra_paths)
    user_message = build_scene_spec_user_message(
        seg_id=seg_id,
        seg_name=seg_name,
        class_name=class_name,
        narration_text=narration_text,
        timing_enrichment=timing_block,
        hints=settings.hints,
        extra_hints=extra_hints,
        reference_scenes=extract_reference_classes(existing),
        source_snippets=snippets,
        word_count=word_count,
    )
    return {
        "settings": settings,
        "seg_name": seg_name,
        "class_name": class_name,
        "narration_text": narration_text,
        "word_count": word_count,
        "system_prompt": scene_spec_system_prompt(cfg, seg_id),
        "user_message": user_message,
        "corpus_text": _corpus_text(narration_text, list(settings.hints), extra_hints, snippets),
        "extra_hints": extra_hints,
    }


def _dry_run_result(ctx: dict[str, Any], seg_id: str) -> Any:
    from docgen.scene_spec_generate import SceneSpecGenerationResult

    prompt = f"--- system ---\n{ctx['system_prompt']}\n\n--- user ---\n{ctx['user_message']}"
    return SceneSpecGenerationResult(
        seg_id=seg_id,
        seg_name=ctx["seg_name"],
        class_name=ctx["class_name"],
        spec={},
        yaml_text="",
        prompt=prompt,
        raw_response="",
    )


def _call_llm(cfg: "Config", invoke: Callable[..., str], **kwargs: Any) -> str:
    try:
        return invoke(**kwargs)
    except RuntimeError as exc:
        from docgen.ai_client import resolve_ai_settings

        settings = resolve_ai_settings(cfg)
        raise SceneGenerationError(
            f"Chat call failed ({exc}). "
            f"{settings.auth_help()} Set DOCGEN_ENV_OVERRIDES=1 to load the bundle "
            "env_file, or use --dry-run to inspect the prompt only."
        ) from exc


def _message_for_attempt(
    user_message: str,
    attempt: int,
    last_sparse: SceneGenerationError | None,
    n_beats: int,
) -> str:
    if attempt == 0 or last_sparse is None:
        return user_message
    err = str(last_sparse)
    if "image prompt alignment" in err:
        return (
            f"{user_message}\n\n--- RETRY: IMAGE PROMPT ALIGNMENT FAILED ---\n"
            f"{last_sparse}\n"
            "Rewrite each image prompt so it uses documented terms from the "
            "narration and SOURCE DOCUMENTATION. Do not invent product names "
            "or generic 'a diagram' artwork with no subject."
        )
    return (
        f"{user_message}\n\n--- RETRY: SUBJECT-BEAT COVERAGE FAILED ---\n"
        f"{last_sparse}\n"
        f"Cover each of the {n_beats} subject beats with a spoken-phrase label. "
        "Hold the board across sentences in the same beat; add a new label only "
        "when the topic shifts. Do not invent unspoken diagram terms."
    )


def _harden_once(cfg: "Config", ctx: dict[str, Any], seg_id: str, raw: str, slack: int) -> dict[str, Any]:
    return _parse_and_harden_llm_spec(
        cfg,
        seg_id=seg_id,
        class_name=ctx["class_name"],
        seg_name=ctx["seg_name"],
        narration_text=ctx["narration_text"],
        word_count=ctx["word_count"],
        raw=raw,
        enforce_density=True,
        density_slack=slack,
        corpus_text=ctx["corpus_text"],
    )


def _alignment_should_stop(exc: SceneGenerationError, attempt: int) -> bool:
    if "image prompt alignment" not in str(exc):
        return False
    return attempt >= 2


def _near_miss_or_raise(
    cfg: "Config",
    ctx: dict[str, Any],
    seg_id: str,
    raw: str,
    near_miss_slack: int,
    attempt: int,
    exc: SceneGenerationError,
) -> tuple[dict[str, Any] | None, SceneGenerationError | None]:
    if "subject-beat coverage" not in str(exc):
        raise exc
    try:
        return _harden_once(cfg, ctx, seg_id, raw, near_miss_slack), None
    except SceneGenerationError as near:
        if "subject-beat coverage" not in str(near) or attempt >= 2:
            raise
        return None, near


def _generate_with_retries(
    cfg: "Config",
    ctx: dict[str, Any],
    seg_id: str,
    *,
    model: str,
    temperature: float,
    invoke: Callable[..., str],
) -> tuple[dict[str, Any], str]:
    n_beats = len(cluster_subject_beats(narration_sentences(ctx["narration_text"])))
    near_miss_slack = max(1, n_beats // 8) if n_beats else 0
    raw = ""
    merged: dict[str, Any] = {}
    last_sparse: SceneGenerationError | None = None
    for attempt in range(3):
        raw = _call_llm(
            cfg,
            invoke,
            system_prompt=ctx["system_prompt"],
            user_message=_message_for_attempt(ctx["user_message"], attempt, last_sparse, n_beats),
            model=model,
            temperature=min(0.9, temperature + 0.15 * attempt),
        )
        try:
            merged = _harden_once(cfg, ctx, seg_id, raw, 0)
            return merged, raw
        except SceneGenerationError as exc:
            if _alignment_should_stop(exc, attempt):
                raise
            if "image prompt alignment" in str(exc):
                last_sparse = exc
                continue
            merged_or_none, last_sparse = _near_miss_or_raise(
                cfg, ctx, seg_id, raw, near_miss_slack, attempt, exc
            )
            if merged_or_none is not None:
                return merged_or_none, raw
    if last_sparse is not None:
        raise last_sparse
    return merged, raw


def _success_result(ctx: dict[str, Any], seg_id: str, merged: dict[str, Any], raw: str) -> Any:
    from docgen.scene_spec_generate import SceneSpecGenerationResult, spec_to_yaml_text

    prompt = f"--- system ---\n{ctx['system_prompt']}\n\n--- user ---\n{ctx['user_message']}"
    return SceneSpecGenerationResult(
        seg_id=seg_id,
        seg_name=ctx["seg_name"],
        class_name=ctx["class_name"],
        spec=merged,
        yaml_text=spec_to_yaml_text(merged),
        prompt=prompt,
        raw_response=raw,
    )


def _resolve_temperature(settings: Any, temperature_override: float | None) -> float:
    if temperature_override is not None:
        return float(temperature_override)
    return float(settings.temperature)


def generate_scene_spec(
    cfg: "Config",
    seg_id: str,
    *,
    extra_paths: list[str],
    extra_hints: list[str],
    class_name_override: str | None = None,
    dry_run: bool = False,
    model_override: str | None = None,
    temperature_override: float | None = None,
    llm: Callable[..., str] | None = None,
) -> Any:
    """Prompt OpenAI for YAML, validate schema, compile+lint the merged Python."""
    from docgen.scene_spec_generate import _invoke_llm

    ctx = _prepare_generation(cfg, seg_id, extra_paths, extra_hints, class_name_override)
    if dry_run:
        return _dry_run_result(ctx, seg_id)
    model = (model_override or "").strip() or ctx["settings"].model
    temperature = _resolve_temperature(ctx["settings"], temperature_override)
    invoke = llm or (lambda **kw: _invoke_llm(cfg=cfg, **kw))
    merged, raw = _generate_with_retries(
        cfg, ctx, seg_id, model=model, temperature=temperature, invoke=invoke
    )
    return _success_result(ctx, seg_id, merged, raw)
