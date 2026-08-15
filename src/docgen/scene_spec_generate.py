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
from docgen.manim_scene_support import (
    SceneGenerationError,
    collect_source_snippets,
    derive_class_name,
    extract_reference_classes,
    merged_scene_generation_settings,
)
from docgen.manim_scene_support import _load_narration as load_narration_for_scene
from docgen.manim_scene_support import _load_timing_segments as load_timing_for_scene
from docgen.manim_primitives import ALLOWED_EMPHASIS, ALLOWED_REVEALS, ALLOWED_SHAPES
from docgen.scene_spec import (
    ALLOWED_COLORS,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    SceneSpecError,
    auto_fit_row_widths,
    auto_paginate,
    coerce_legacy_wait_at_to_whisper_rows,
    sanitize_pacing_conflicts,
    compile_scene_class,
    cluster_subject_beats,
    layout_budget_violations,
    layout_density_violations,
    layout_stack_budget,
    narration_sentences,
    spec_rows_reference_whisper_waits,
    pacing_violations,
    sync_row_labels_to_whisper_words,
    upgrade_wait_segments_to_wait_words,
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
- title: mapping with text (string), font_size (int, >= 14), color (one of the palette tokens below);
  optional subtitle (string ≤80 chars) for a second line under the title
- **Exactly one of:** ``rows`` (non-empty list of row mappings, single page) **or** ``pages`` (non-empty list of page mappings; each page has ``rows`` as above, optionally ``transition``: fade | none for pages after the first)

Each row must have:
- run_time: positive number (seconds for timed_play FadeIn of **each** box in that row)
- boxes: non-empty list of box mappings, each with:
  - label: string (spoken phrase — used for wait_word matching)
  - color: one of the palette tokens
  - width: positive number (typical 2.0–6.0; safe row total ≤ ~13 wide at dogfood resolution)
  - height: positive number (typical 0.65–1.1; **smaller when a page has many rows**)
  - font_size: int >= 14
  - subtitle: optional second line ≤60 chars (decorative; not used for beat matching)
  - shape: optional rounded (default) | pill | diamond — use diamond for decisions, pill for states
  - reveal: optional fade (default) | grow | slide — grow for the first node of a flow; slide for a new row
  - emphasis: optional none | pulse | ring — omit to inherit layout.dwell_emphasis (auto = pulse when the
    hold until the next wait_word is long enough). The compiler clamps emphasis so it cannot race the clock.

Optional **image elements** (only when project-owner hints ask for generated imagery): a ``boxes`` entry
may instead be an image element with:
  - image: bundle-relative asset path, e.g. ``images/<short-name>.png`` (no absolute paths, no "..")
  - width / height: positive numbers (frame budget rules above apply; images count like boxes)
  - prompt: string — a clear visual description; ``docgen image-generate`` renders it via the OpenAI Images API
  - label: optional single word from the narration used as the timing anchor for the reveal
Image elements must NOT carry ``color`` or ``font_size``. Prefer labeled boxes for diagrams; use images
only for illustrative artwork the hints explicitly request.

Optional per-box (**Whisper ``words`` only**); omit if unsure — compile fills from each box ``label`` → first transcript match:
- wait_word: non-negative int — index into ``timing.json`` → ``words``; that box waits until that token's **start**, then fades in (**one box at a time** within each row).
- pace: optional ``none`` — opt out of beat sync for that box (rare; decorative only). When timing
  words exist, every other labeled box **must** match a spoken phrase or compile fails.

Optional per-row (legacy; first box only — prefer per-box above):
- wait_word: non-negative int — if set, and boxes omit ``wait_word``, only the **first** box in the row uses this index.
- pace: optional ``none`` — opt out for every box in the row.

Optional top-level:
- layout: optional first_row_title_buff, row_gap, column_gap (positive numbers);
  for multi-page specs also page_transition: fade | none (default fade), page_transition_run_time (default 0.45, max 5);
  dwell_emphasis: auto (default; pulse during long holds) | none; dwell_run_time: seconds for that pulse (default 0.5, max 3).
- edges: optional list of connectors for **single-page** ``rows`` specs (see below).

Optional per-page (when using ``pages``):
- edges: list of {{ from: <box label>, to: <box label>, color?: <palette token>,
  style?: solid|dashed, label?: short edge caption ≤40 chars }}
  drawn as arrows between those boxes after layout. Box labels must be unique on that page.
  Prefer edges for pipeline / flow diagrams (A → B → C); omit when boxes are unrelated topics.

Use either **rows** (single page) OR **pages** (list of {{ rows: [...], transition?: fade|none, edges?: [...] }} — transition on pages after the first overrides layout.page_transition for exiting the previous page; first page has no transition in).

Palette tokens (exact spelling): {", ".join(sorted(ALLOWED_COLORS))}

Design goals:
- **Frame:** dogfood Manim canvas is ~14.22 × 8 units; title + buffer eat the top — see user-message budget. Never stack so many tall rows that boxes would clip off the bottom.
- **Do not** rely on shrinking: split into **pages** with fade between them.
- **Rows** within a page stack vertically; multiple boxes in one row arrange horizontally with safe spacing.
- **Edges / arrows:** when narration describes a flow or pipeline, add ``edges`` so the board shows
  directed connections (not only isolated boxes). Keep edge endpoints as spoken labels.
  Use ``style: dashed`` for optional/secondary paths and a short ``label`` on the arrow when
  the narration names the relationship (keep edge captions terse). Arrows attach to box **edges**,
  not centers.
- **Motion (keep labels spoken):** vary ``shape`` / ``reveal`` / ``emphasis`` instead of inventing
  extra labels. Prefer ``reveal: grow`` on the first node of a pipeline and ``emphasis: ring`` on
  a decision diamond. Do **not** add boxes just to fill time — the toolchain pulses a revealed
  box during a long subject-beat hold.
  Allowed shapes: {", ".join(sorted(ALLOWED_SHAPES))}; reveals: {", ".join(sorted(ALLOWED_REVEALS))};
  emphasis: {", ".join(sorted(ALLOWED_EMPHASIS))}.
- **Subject-beat coverage (mandatory):** consecutive sentences on the same topic are one beat —
  **hold the board**. When the topic shifts, reveal a new spoken-phrase label for that beat.
  Do **not** invent a box per sentence, and do **not** leave a new topic without a matching label.
  The toolchain checks **coverage of subject beats** (and rejects invented unspoken labels),
  not a blind label count.
- Mirror **narration**; each box label must be a short phrase **copied from the spoken
  narration** (toolchain sets ``wait_word`` from label → first transcript match when you omit indices).
- Keep labels concise (2–5 words); do not invent diagram-only jargon that is not spoken.
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
    from docgen.manim_scene_support import call_llm

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
    timing_enrichment: str,
    hints: list[str],
    extra_hints: list[str],
    reference_scenes: str,
    source_snippets: list[tuple[str, str]],
    word_count: int = 0,
) -> str:
    """User message: narration + timing + hints; demand YAML spec."""
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
    beats = cluster_subject_beats(narration_sentences(narration_text))
    if beats:
        wc_note = f" ({word_count} Whisper words)" if word_count > 0 else ""
        parts.append(
            f"**SUBJECT BEATS{wc_note} — cover each with ≥1 spoken-phrase label "
            f"(hold the board inside a beat; change when the topic shifts):**"
        )
        for i, beat in enumerate(beats, start=1):
            preview = beat if len(beat) <= 160 else beat[:157] + "..."
            parts.append(f"  {i}. {preview}")
        parts.append(
            "scene-spec-generate **rejects** specs that leave beats uncovered or use "
            "labels that are not spoken in the narration (not a blind label count)."
        )
        parts.append("")
    parts.append(timing_enrichment.strip())

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
    horiz_safe = FRAME_WIDTH - 1.0
    budget_default = layout_stack_budget(
        {"font_size": 36}, {"first_row_title_buff": 0.5}
    )
    budget_compact = layout_stack_budget(
        {"font_size": 32}, {"first_row_title_buff": 0.45}
    )
    parts.append(
        f"Frame ≈ {FRAME_WIDTH:.2f} × {FRAME_HEIGHT:.2f} Manim units. "
        f"Horizontal safe width ≈ {horiz_safe:.2f} u "
        "(sum of box widths + (n_boxes-1)*column_gap per row must stay ≤ this)."
    )
    parts.append(
        "**Vertical stack budgets** (use these numbers unless you change "
        "title.font_size / layout.first_row_title_buff):\n"
        f"  • Default font_size=36, first_row_title_buff=0.5 → "
        f"max stack height ≈ {budget_default:.2f} u\n"
        f"  • Compact font_size=32, first_row_title_buff=0.45 → "
        f"max stack height ≈ {budget_compact:.2f} u\n"
        "Per page: sum(max box height per row) + (n_rows-1)*row_gap ≤ that budget. "
        "When you would exceed it, spill to another page (do not shrink/cram)."
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
    from docgen.manim_scene_support import SceneGenerationError, lint_generated_block

    merged = dict(spec)
    sid = str(merged["segment_id"]).strip()
    if timing_key is not None:
        merged["timing_key"] = timing_key
    elif not merged.get("timing_key"):
        merged["timing_key"] = cfg.resolve_segment_name(sid)

    # Engine-side layout planning + audio sync so authored YAML stays minimal.
    merged = auto_fit_row_widths(merged)
    merged = auto_paginate(merged)
    tk = str(merged["timing_key"])
    segments = load_timing_for_scene(cfg, tk)
    words = _load_timing_words(cfg, tk)
    merged = coerce_legacy_wait_at_to_whisper_rows(merged, words, segments)
    if words and segments:
        merged = upgrade_wait_segments_to_wait_words(merged, words, segments)
    if words:
        # LLM-authored wait_word values are often wrong (duplicates / guesses). Compile
        # always re-derives indices from each box label + transcript order so multi-box
        # rows reveal one box at a time. Fail-closed: unmatched labels clear wait_word
        # and are rejected below (no leftover LLM indices, no fuzzy false positives).
        merged = sync_row_labels_to_whisper_words(merged, words, overwrite=True)

    if spec_rows_reference_whisper_waits(merged) and not words:
        raise SceneGenerationError(
            f"timing.json has no word-level `words` for stem {tk!r}; run `docgen timestamps` "
            "before compiling scenes that use wait_word or wait_segment."
        )

    pace_issues = pacing_violations(merged, words_present=bool(words))
    if pace_issues:
        shown = "\n  ".join(pace_issues[:12])
        more = f"\n  (+{len(pace_issues) - 12} more)" if len(pace_issues) > 12 else ""
        raise SceneGenerationError(
            f"scene pacing failed for timing_key {tk!r} — every story box needs a "
            f"spoken label matched in timing.json words (or pace: none):\n  {shown}{more}"
        )

    try:
        # Pass Whisper words so compile clamps FadeIn/page-fade run_times against
        # the next wait_word (issue #66 — do not emit clock-racing garbage).
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
    from docgen.manim_scene_support import (
        SceneGenerationError,
        ensure_image_helper,
        ensure_scenes_bootstrap,
        inject_or_replace,
        refresh_bootstrap_helpers,
    )

    scenes_path = cfg.animations_dir / "scenes.py"
    try:
        ensure_scenes_bootstrap(scenes_path)
        refresh_bootstrap_helpers(scenes_path)
        if "_image(" in class_block:
            ensure_image_helper(scenes_path)
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


def _parse_and_harden_llm_spec(
    cfg: Config,
    *,
    seg_id: str,
    class_name: str,
    seg_name: str,
    narration_text: str,
    word_count: int,
    raw: str,
    enforce_density: bool,
    density_slack: int = 0,
) -> dict[str, Any]:
    """Parse YAML, auto-layout, validate schema/budget/(optional) density, compile-lint."""
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
    merged_spec = auto_fit_row_widths(merged_spec)
    merged_spec = auto_paginate(merged_spec)
    merged_spec = sanitize_pacing_conflicts(merged_spec)
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

    if enforce_density and getattr(cfg, "subject_beat_coverage_enabled", True):
        density_issues = layout_density_violations(
            merged_spec,
            narration_text=narration_text,
            word_count=word_count,
            slack=density_slack,
        )
        if density_issues:
            draft = _save_draft(cfg, seg_id, body)
            joined = "\n  ".join(density_issues)
            raise SceneGenerationError(
                f"segment {seg_id}: scene spec failed subject-beat coverage:\n  {joined}\nDraft: {draft}"
            )

    try:
        _, _ = linted_class_block_from_spec(cfg, merged_spec, timing_key=seg_name)
    except SceneGenerationError as exc:
        draft = _save_draft(cfg, seg_id, body)
        raise SceneGenerationError(f"{exc} Draft: {draft}") from exc
    return merged_spec


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
    from docgen.manim_scene_support import build_timing_enrichment_for_prompt

    timing_block = build_timing_enrichment_for_prompt(cfg, seg_id, seg_name, whisper_segments)
    word_count = len(_load_timing_words(cfg, seg_name))

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
        timing_enrichment=timing_block,
        hints=settings.hints,
        extra_hints=extra_hints,
        reference_scenes=reference_scenes,
        source_snippets=snippets,
        word_count=word_count,
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
    n_beats = len(cluster_subject_beats(narration_sentences(narration_text)))
    # Near-miss: allow a couple uncovered beats after retry, not a blind label quota.
    near_miss_slack = max(1, n_beats // 8) if n_beats else 0
    raw = ""
    merged_spec: dict[str, Any] = {}
    last_sparse: SceneGenerationError | None = None
    for attempt in range(3):
        msg = user_message
        if attempt > 0 and last_sparse is not None:
            msg = (
                f"{user_message}\n\n--- RETRY: SUBJECT-BEAT COVERAGE FAILED ---\n"
                f"{last_sparse}\n"
                f"Cover each of the {n_beats} subject beats with a spoken-phrase label. "
                "Hold the board across sentences in the same beat; add a new label only "
                "when the topic shifts. Do not invent unspoken diagram terms."
            )
        try:
            raw = invoke(
                system_prompt=system_prompt,
                user_message=msg,
                model=model,
                temperature=min(0.9, temperature + 0.15 * attempt),
            )
        except RuntimeError as exc:
            raise SceneGenerationError(
                f"OpenAI/chat call failed ({exc}). "
                "Check OPENAI_API_KEY, set DOCGEN_ENV_OVERRIDES=1 to load the bundle env_file, "
                "or use --dry-run to inspect the prompt only."
            ) from exc
        try:
            merged_spec = _parse_and_harden_llm_spec(
                cfg,
                seg_id=seg_id,
                class_name=class_name,
                seg_name=seg_name,
                narration_text=narration_text,
                word_count=word_count,
                raw=raw,
                enforce_density=True,
                density_slack=0,
            )
            last_sparse = None
            break
        except SceneGenerationError as exc:
            if "subject-beat coverage" not in str(exc):
                raise
            # Near-miss: accept without another LLM call when close enough.
            try:
                merged_spec = _parse_and_harden_llm_spec(
                    cfg,
                    seg_id=seg_id,
                    class_name=class_name,
                    seg_name=seg_name,
                    narration_text=narration_text,
                    word_count=word_count,
                    raw=raw,
                    enforce_density=True,
                    density_slack=near_miss_slack,
                )
                last_sparse = None
                break
            except SceneGenerationError as near:
                if "subject-beat coverage" not in str(near) or attempt >= 2:
                    raise
                last_sparse = near
                continue
    if last_sparse is not None:
        raise last_sparse

    yaml_text = spec_to_yaml_text(merged_spec)
    return SceneSpecGenerationResult(
        seg_id=seg_id,
        seg_name=seg_name,
        class_name=class_name,
        spec=merged_spec,
        yaml_text=yaml_text,
        prompt=f"--- system ---\n{system_prompt}\n\n--- user ---\n{user_message}",
        raw_response=raw,
    )
