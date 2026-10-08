"""LLM-driven **scene spec YAML** for ``docgen scene-spec-generate``.

The model emits only structured YAML validated by :mod:`docgen.scene_spec`, then
``docgen scene-compile`` (or ``--compile``) turns it into layout-safe Manim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from docgen.openai_retry import call_with_rate_limit_retries
from docgen.manim_scene_support import (
    SceneGenerationError,
)
from docgen.manim_primitives import ALLOWED_EMPHASIS, ALLOWED_REVEALS, ALLOWED_SHAPES
from docgen.scene_spec import (
    ALLOWED_COLORS,
)

if TYPE_CHECKING:
    from docgen.config import Config

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
  - prompt: string — a clear visual description grounded in the narration **and** SOURCE
    DOCUMENTATION; ``docgen image-generate`` renders it and rejects prompts that invent
    undocumented product names or share no documented terms
  - label: optional spoken phrase from the narration used as the timing anchor for the reveal
Image elements must NOT carry ``color`` or ``font_size``. Prefer labeled boxes for diagrams; use images
only for illustrative artwork the hints explicitly request. Image ``prompt`` text must name
the same concepts as the narration/source (not generic "a diagram" / invented architecture).
Any words you expect to appear *inside* the artwork must be short ASCII copied from the docs.

Optional per-box (**Whisper ``words`` only**); omit if unsure — compile fills from each box ``label`` → first transcript match:
- wait_word: non-negative int — index into ``timing.json`` → ``words``; that box waits until that token's **start**, then fades in (**one box at a time** within each row).
- pace: optional ``none`` — opt out of beat sync for that box (rare; decorative only). When timing
  words exist, every other labeled box **must** match a spoken phrase or compile fails.

Optional per-row (legacy; first box only — prefer per-box above):
- wait_word: non-negative int — if set, and boxes omit ``wait_word``, only the **first** box in the row uses this index.
- pace: optional ``none`` — opt out for every box in the row.

Optional top-level:
- layout: optional first_row_title_buff, row_gap, column_gap (positive numbers);
  for multi-page specs also page_transition: fade | slide | none (default fade), page_transition_run_time (default 0.45, max 5);
  dwell_emphasis: auto (default; pulse during long holds) | none; dwell_run_time: seconds for that pulse (default 0.5, max 3).
- edges: optional list of connectors for **single-page** ``rows`` specs (see below).

Optional per-page (when using ``pages``):
- edges: list of {{ from: <box label>, to: <box label>, color?: <palette token>,
  style?: solid|dashed, label?: short edge caption ≤40 chars }}
  drawn as arrows between those boxes after layout. Box labels must be unique on that page.
  Prefer edges for pipeline / flow diagrams (A → B → C); omit when boxes are unrelated topics.

Use either **rows** (single page) OR **pages** (list of {{ rows: [...], transition?: fade|slide|none, edges?: [...] }} — transition on pages after the first overrides layout.page_transition for exiting the previous page; first page has no transition in). Prefer ``slide`` when the next page continues the same pipeline.

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
  box at the start of a long subject-beat hold and again before the board would sit still.
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
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    cfg: "Config | None" = None,
) -> str:
    from docgen.manim_scene_support import call_llm

    return call_with_rate_limit_retries(
        lambda: call_llm(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            temperature=temperature,
            cfg=cfg,
        )
    )


def build_scene_spec_user_message(*args, **kwargs):
    """User message: narration + timing + hints; demand YAML spec."""
    from docgen.scene_spec_flow import build_scene_spec_user_message as _impl
    return _impl(*args, **kwargs)


@dataclass
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
    """Return the ``words`` list from ``animations/timing.json`` for ``timing_key``."""
    from docgen.timestamps import TimestampError, load_bundle_timing

    try:
        data = load_bundle_timing(cfg)
    except TimestampError as exc:
        raise SceneGenerationError(str(exc)) from exc
    block = data.get(timing_key)
    if not isinstance(block, dict):
        return []
    words = block.get("words")
    return list(words) if isinstance(words, list) else []


def linted_class_block_from_spec(*args, **kwargs):
    """Merge timing_key, auto-paginate + word-align, compile, lint."""
    from docgen.scene_spec_flow import linted_class_block_from_spec as _impl
    return _impl(*args, **kwargs)


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


def _parse_and_harden_llm_spec(*args, **kwargs):
    """Parse YAML, auto-layout, validate, compile-lint."""
    from docgen.scene_spec_flow import _parse_and_harden_llm_spec as _impl
    return _impl(*args, **kwargs)


def generate_scene_spec(*args, **kwargs):
    """Prompt for YAML, validate schema, compile+lint the merged Python."""
    from docgen.scene_spec_flow import generate_scene_spec as _impl
    return _impl(*args, **kwargs)


