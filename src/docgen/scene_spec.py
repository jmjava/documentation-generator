"""Declarative Manim scene specs (YAML) compiled to compliant Python.

LLMs are poor at reliable 2D layout in raw Manim code.  Instead they (or
humans) author a small **scene spec** — rows of labeled boxes, colors, and
optional ``wait_word`` indices on each **box** into the Whisper **words** list in ``timing.json``
(wait until that token's ``start``). Rows may still carry legacy ``wait_segment`` or a single
``wait_word`` (applied only to the **first** box in that row after compile). On-disk YAML may
still list legacy ``wait_segment``; ``docgen scene-compile`` upgrades those to the first box's
``wait_word`` when ``words`` exist and writes the YAML back so compile cannot leave a key it rejects.
``class ...(_TimedScene)`` body that:

* Lays out each **page** as a vertical stack of rows (``VGroup`` per row,
  then ``arrange(DOWN)``), positioned under the title — **no scaling** to cram
  content; use multiple **pages** when the story needs more boxes than fit.
* Between pages, runs a **page transition** so the next page appears on a
  clear canvas. ``fade`` (default) dissolves the previous board. ``slide``
  travels it off to the left and brings the next page's first node in from
  the right. ``rise`` drops the board and settles the next node from above.
  ``zoom`` shrinks the board away and scales the next node up. ``none``
  removes the previous board instantly. Later boxes on the incoming page
  stay paced — the handoff does not dump the whole next board.
* Uses the shared ``_box`` helper (text centered in the node; optional
  ``shape`` / ``reveal`` / ``emphasis``). After each paced reveal, a **dwell**
  slot may play ``Indicate`` / ``Circumscribe`` when the gap to the next
  ``wait_word`` is long enough — clamped so ``_clock`` cannot race. Long
  holds schedule **additional** mid-hold pulses (``timed_wait`` + emphasis)
  so the board does not freeze after the first Indicate. The last box uses
  the audio tail as its deadline. Every compiled ``Text()`` sets
  ``font=MANIM_FONT``. ``docgen validate`` ``scene_assets`` re-checks
  cadence, hold idle, frame budget, helpers, and compile sync before a render.

Typical workflow:

1. ``docgen scene-spec-generate --segment <id> --config docgen.yaml`` (YAML under ``animations/specs/``),
   or author ``animations/specs/<stem>.scene.yaml`` by hand.
2. ``docgen scene-compile path/to/spec.scene.yaml --config docgen.yaml`` (if not using ``--compile``).
3. ``docgen timestamps`` → ``docgen manim`` as usual.

``docgen scene-spec-generate`` also runs :func:`layout_budget_violations` (frame fit) and
:func:`layout_density_violations` (**subject-beat coverage**: hold the board across sentences
on the same topic; cover each topic shift with a spoken-phrase label; reject invented labels —
not a blind label count). ``docgen validate`` re-checks coverage when a ``*.scene.yaml`` exists.
``scene-compile`` does not enforce layout budget (hand fixes allowed).
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from docgen.manim_primitives import (
    ALLOWED_DWELL_EMPHASIS,
    ALLOWED_EMPHASIS,
    ALLOWED_REVEALS,
    ALLOWED_SHAPES,
    DEFAULT_DWELL_RUN_TIME,
    HoldPulse,
    MIN_DWELL_RUN_TIME,
    audio_end_from_words,
    clamp_title_run_time,
    hold_span_seconds,
    plan_hold_pulses,
    resolve_box_emphasis,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Compiled scenes Write the title then pace boxes with wait_until_word against
# ``_TimedScene._clock``. Keep the title short so early Whisper starts are not
# already in the past before the first box reveal.
TITLE_WRITE_RUN_TIME = 1.0
# Floor when clamping FadeIn so the clock cannot overshoot the next wait_word.
MIN_REVEAL_RUN_TIME = 0.25

ALLOWED_COLORS = frozenset(
    {
        "C_BG",
        "C_ACCENT",
        "C_GREEN",
        "C_ORANGE",
        "C_BLUE",
        "C_RED",
        "C_TEAL",
        "C_PURPLE",
        "C_WHITE",
    }
)

# Order is the author-facing set. ``fade`` stays the default so a topic change
# stays a dissolve; slide / rise / zoom are the animated handoffs.
PAGE_TRANSITION_ORDER = ("fade", "slide", "rise", "zoom", "none")
ALLOWED_PAGE_TRANSITIONS = frozenset(PAGE_TRANSITION_ORDER)
# Animated exits advance ``_TimedScene._clock``. ``none`` is an instant remove.
ANIMATED_PAGE_TRANSITIONS = frozenset({"fade", "slide", "rise", "zoom"})
# Manim frame is ~14.22 x 8. A 0.35 nudge barely left the center; these shifts
# carry a centered row off the focal area while the fade finishes.
PAGE_SLIDE_SHIFT = 3.2
# Exit drops the old board. The entrance is shorter than ``MIN_TITLE_ROW_BUFF``
# so the incoming node starts under the title instead of crossing it.
PAGE_RISE_SHIFT = 1.6
PAGE_RISE_ENTER = 0.28
PAGE_ZOOM_SCALE = 0.15


def _is_yaml_number(value: Any) -> bool:
    """YAML number: int/float, not bool (``bool`` is a subclass of ``int``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_yaml_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# Spec-geometry floors — tighter than this and boxes collide or sit on the title.
MIN_TITLE_ROW_BUFF = 0.35
MIN_ROW_GAP = 0.2
MIN_COLUMN_GAP = 0.2
ALLOWED_EDGE_STYLES = frozenset({"solid", "dashed"})

SPEC_REQUIRED_TOP = ("segment_id", "class_name", "title")

# Match ``scenes.py`` dogfood header: frame width × height in Manim units.
FRAME_WIDTH = 14.22
FRAME_HEIGHT = 8.0
# Horizontal band left clear of rounded boxes at edge; vertical margin above y = -4.
_LAYOUT_HORIZONTAL_SAFE = FRAME_WIDTH - 1.0
_LAYOUT_BOTTOM_MARGIN = 0.55


def _title_band_estimate(font_size: int, *, has_subtitle: bool = False) -> float:
    """Rough vertical space from top of frame through title and first gap."""
    fs = max(14, int(font_size))
    band = 0.78 + (fs / 36.0) * 0.52
    if has_subtitle:
        band += 0.38
    return band


def layout_stack_budget(title: dict[str, Any], layout: dict[str, Any] | None) -> float:
    """Max total row-stack height (Manim units) that fits below ``title`` without clipping."""
    layout = layout or {}
    buff = float(layout.get("first_row_title_buff", 0.5))
    fs = title.get("font_size")
    if not _is_yaml_number(fs):
        fs = 36
    has_sub = bool(str(title.get("subtitle") or "").strip())
    band = _title_band_estimate(int(fs), has_subtitle=has_sub)
    return FRAME_HEIGHT - band - buff - _LAYOUT_BOTTOM_MARGIN


def _spec_pages_rows(spec: dict[str, Any]) -> list[list[dict[str, Any]]]:
    if spec.get("pages") is not None:
        pages_raw = spec["pages"]
        if not isinstance(pages_raw, list):
            return []
        out: list[list[dict[str, Any]]] = []
        for p in pages_raw:
            if isinstance(p, dict):
                r = p.get("rows")
                if isinstance(r, list):
                    out.append(list(r))
        return out
    r0 = spec.get("rows")
    if isinstance(r0, list) and r0:
        return [list(r0)]
    return []


def iter_image_elements(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """All **image elements** (boxes with an ``image:`` key) across rows/pages, in order."""
    out: list[dict[str, Any]] = []
    for rows in _spec_pages_rows(spec):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for box in row.get("boxes") or []:
                if _is_image_element(box):
                    out.append(box)
    return out


def _row_height(row: dict[str, Any]) -> float:
    boxes = row.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        return 0.0
    try:
        return max(float(b["height"]) for b in boxes if isinstance(b, dict))
    except (KeyError, TypeError, ValueError):
        return 0.0


def _row_width(row: dict[str, Any], col_gap: float) -> float:
    boxes = row.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        return 0.0
    try:
        ws = [float(b["width"]) for b in boxes if isinstance(b, dict)]
    except (KeyError, TypeError, ValueError):
        return 0.0
    if not ws:
        return 0.0
    return sum(ws) + max(0, len(ws) - 1) * col_gap


def _fit_row_width(boxes: list[dict[str, Any]], col_gap: float) -> float:
    ws = [float(b.get("width", 0)) for b in boxes]
    if not ws:
        return 0.0
    return sum(ws) + max(0, len(ws) - 1) * col_gap


def _scaled_box_widths(
    boxes: list[dict[str, Any]], scale: float, min_box_w: float
) -> list[dict[str, Any]]:
    scaled: list[dict[str, Any]] = []
    for box in boxes:
        copied = dict(box)
        try:
            copied["width"] = max(min_box_w, float(box["width"]) * scale)
        except (KeyError, TypeError, ValueError):
            pass
        scaled.append(copied)
    return scaled


def _chunk_boxes_to_width(
    boxes: list[dict[str, Any]],
    *,
    safe: float,
    col_gap: float,
    min_box_w: float,
) -> list[list[dict[str, Any]]]:
    """Split a still-too-wide row into chunks of at most three, then scale each."""
    chunks: list[list[dict[str, Any]]] = []
    for i in range(0, len(boxes), 3):
        part = [dict(b) for b in boxes[i : i + 3]]
        prw = _fit_row_width(part, col_gap)
        if prw > safe + 0.05 and prw > 0:
            part = _scaled_box_widths(part, safe / prw, min_box_w)
        chunks.append(part)
    return chunks


def _fit_boxes_to_width(
    boxes: list[dict[str, Any]],
    *,
    safe: float,
    col_gap: float,
    min_box_w: float,
) -> list[list[dict[str, Any]]]:
    if not boxes:
        return []
    rw = _fit_row_width(boxes, col_gap)
    if rw <= safe + 0.05:
        return [boxes]
    scale = safe / rw if rw > 0 else 1.0
    scaled = _scaled_box_widths(boxes, scale, min_box_w)
    if _fit_row_width(scaled, col_gap) <= safe + 0.05:
        return [scaled]
    return _chunk_boxes_to_width(boxes, safe=safe, col_gap=col_gap, min_box_w=min_box_w)


def auto_fit_row_widths(spec: dict[str, Any]) -> dict[str, Any]:
    """Scale or split rows that exceed the horizontal safe width.

    Prefer proportional width scaling (keeps the author's row composition). If a row
    still cannot fit (too many boxes even at a floor width), split it into chunks of
    at most three boxes so ``layout_budget_violations`` can pass after LLM drafts.
    """
    layout = spec.get("layout") if isinstance(spec.get("layout"), dict) else {}
    col_gap = float(layout.get("column_gap", 0.8))
    safe = _LAYOUT_HORIZONTAL_SAFE
    min_box_w = 1.6

    def _fit_boxes(boxes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        return _fit_boxes_to_width(boxes, safe=safe, col_gap=col_gap, min_box_w=min_box_w)

    def _rewrite_rows(rows: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            boxes = row.get("boxes")
            if not isinstance(boxes, list) or not boxes:
                out.append(dict(row))
                continue
            clean = [b for b in boxes if isinstance(b, dict)]
            fitted = _fit_boxes(clean)
            if len(fitted) == 1:
                nr = dict(row)
                nr["boxes"] = fitted[0]
                out.append(nr)
            else:
                for bi, chunk in enumerate(fitted):
                    nr = dict(row)
                    nr["boxes"] = chunk
                    if bi > 0:
                        nr.pop("wait_word", None)
                        nr.pop("wait_segment", None)
                        nr.pop("wait_at", None)
                    out.append(nr)
        return out

    out = dict(spec)
    if out.get("pages") is not None:
        new_pages: list[Any] = []
        for page in out["pages"]:
            if not isinstance(page, dict):
                new_pages.append(page)
                continue
            p = dict(page)
            rows = p.get("rows")
            if isinstance(rows, list):
                p["rows"] = _rewrite_rows(rows)
            new_pages.append(p)
        out["pages"] = new_pages
    elif isinstance(out.get("rows"), list):
        out["rows"] = _rewrite_rows(out["rows"])
    return out


def _paginate_source_pages(
    spec: dict[str, Any], transition_default: str
) -> list[tuple[list[dict[str, Any]], str | None]] | None:
    """Rows plus the transition that should lead each source page (``None`` when absent)."""
    if spec.get("pages") is not None:
        src_pages: list[tuple[list[dict[str, Any]], str | None]] = []
        for pi, page in enumerate(spec["pages"]):
            if not isinstance(page, dict):
                continue
            rows = page.get("rows")
            if not isinstance(rows, list) or not rows:
                continue
            tr = None if pi == 0 else str(page.get("transition", transition_default))
            src_pages.append((list(rows), tr))
        return src_pages
    rows = spec.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    return [(list(rows), None)]


def _split_rows_to_pages(
    rows: list[dict[str, Any]], *, budget: float, row_gap: float
) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_h = 0.0
    for row in rows:
        rh = _row_height(row)
        if not current:
            current.append(row)
            current_h = rh
            continue
        projected = current_h + row_gap + rh
        if projected > budget + 0.02:
            out.append(current)
            current = [row]
            current_h = rh
        else:
            current.append(row)
            current_h = projected
    if current:
        out.append(current)
    return out


def _paginate_page_entry(
    *,
    page_idx: int,
    chunk_idx: int,
    chunk: list[dict[str, Any]],
    tr: str | None,
    transition_default: str,
) -> dict[str, Any]:
    """First chunk of the first source page has no transition; later chunks hand off."""
    entry: dict[str, Any] = {"rows": chunk}
    if page_idx == 0 and chunk_idx == 0:
        return entry
    if chunk_idx == 0 and tr is not None:
        entry["transition"] = tr
    else:
        entry["transition"] = transition_default
    return entry


def _finish_paginated_spec(
    spec: dict[str, Any], new_pages: list[dict[str, Any]]
) -> dict[str, Any]:
    # If nothing changed (single page, no split), keep the original ``rows`` form.
    only_one = len(new_pages) == 1 and "transition" not in new_pages[0]
    if only_one and spec.get("rows") is not None and spec.get("pages") is None:
        return spec
    new_spec = dict(spec)
    new_spec.pop("rows", None)
    new_spec["pages"] = new_pages
    return new_spec


def auto_paginate(spec: dict[str, Any]) -> dict[str, Any]:
    """Re-paginate a spec so every page fits the Manim frame.

    The engine accepts a flat ``rows:`` (intent) or hand-carved ``pages:`` (override). When the
    rows on any page exceed the vertical stack budget — derived from ``title.font_size`` and
    ``layout.first_row_title_buff`` — they are split greedily into additional pages with the
    same ``layout.page_transition`` (default fade). Specs that already fit are returned unchanged.
    """
    title = spec.get("title")
    if not isinstance(title, dict):
        return spec
    layout = spec.get("layout") or {}
    if not isinstance(layout, dict):
        layout = {}
    try:
        budget = layout_stack_budget(title, layout)
    except (TypeError, ValueError):
        return spec
    row_gap = float(layout.get("row_gap", 0.6))
    transition_default = str(layout.get("page_transition", "fade"))
    src_pages = _paginate_source_pages(spec, transition_default)
    if src_pages is None:
        return spec
    new_pages = [
        _paginate_page_entry(
            page_idx=page_idx,
            chunk_idx=chunk_idx,
            chunk=chunk,
            tr=tr,
            transition_default=transition_default,
        )
        for page_idx, (rows, tr) in enumerate(src_pages)
        for chunk_idx, chunk in enumerate(
            _split_rows_to_pages(rows, budget=budget, row_gap=row_gap)
        )
    ]
    return _finish_paginated_spec(spec, new_pages)


def _normalize_word(s: str) -> str:
    """Lowercased, alnum-only word for first-mention matching."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _label_tokens(label: str) -> list[str]:
    """Tokenize a diagram label for Whisper matching.

    Splits on whitespace **and** hyphens/underscores so ``yaml-generate`` can
    align to spoken ``yaml`` + ``generate`` (not only the glued ``yamlgenerate``).
    """
    parts = re.split(r"[\s\-_]+", str(label).strip())
    return [t for t in (_normalize_word(p) for p in parts) if t]


# Suffix list for cheap English stemming when matching scene labels to spoken words.
# Order matters: longer / more specific suffixes are checked before generic ones (e.g. "ing"
# before "s", "es" before "s", "tion" before "s") so "tracing" -> "trac" not "tracin".
_LABEL_STEM_SUFFIXES = (
    "ing",
    "tions",
    "tion",
    "ies",
    "edly",
    "ed",
    "ly",
    "es",
    "s",
    "e",
)


def _stem(token: str) -> str:
    """Cheap English stem for label↔word matching (e.g. ``trace`` and ``tracing`` share ``trac``)."""
    if len(token) < 5:
        return token
    for suf in _LABEL_STEM_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            return token[: -len(suf)]
    return token


def _tokens_match(label_token: str, word_token: str) -> bool:
    """True when the spoken ``word_token`` should be considered an instance of ``label_token``.

    Exact normalized equality always wins. For tokens long enough to be unambiguous (≥ 4 chars
    on both sides) we additionally accept matching English stems so ``Trace`` aligns to ``tracing``,
    ``Compose`` to ``composing``, etc. Short product names like ``TTS`` keep their strict match.
    """
    if label_token == word_token:
        return True
    if len(label_token) < 4 or len(word_token) < 4:
        return False
    return _stem(label_token) == _stem(word_token)


def _glued_compound_span(tokens: list[str], ti: int, spoken: str) -> int | None:
    """How many label tokens glue into one Whisper word, or ``None`` if they do not.

    Spoken words are longer only when TTS/Whisper glued extra chars we already
    normalized away (rare); compounds require exact equality.
    """
    glued = tokens[ti]
    for k in range(2, len(tokens) - ti + 1):
        glued += tokens[ti + k - 1]
        if glued == spoken:
            return k
        if len(glued) > len(spoken):
            return None
    return None


def _consume_label_tokens_at(
    tokens: list[str],
    word_norms: list[str],
    start: int,
) -> int | None:
    """Advance through ``word_norms`` from ``start`` until all ``tokens`` are consumed.

    Whisper often emits hyphenated compounds as **one** token (``version-controlled`` →
    ``versioncontrolled``, ``setup-agent-prompts.sh`` → ``setupagentpromptssh``) while
    labels split on hyphens into multiple tokens. Accept either:

    - one label token ↔ one spoken word (exact / stem), or
    - two or more consecutive label tokens glued ↔ one spoken word.

    Returns the index of the last consumed spoken word, or ``None`` if the label
    cannot be matched starting at ``start``.
    """
    if not tokens or start < 0 or start >= len(word_norms):
        return None
    ti = 0
    wi = start
    m = len(tokens)
    n = len(word_norms)
    while ti < m:
        if wi >= n:
            return None
        spoken = word_norms[wi]
        if _tokens_match(tokens[ti], spoken):
            ti += 1
            wi += 1
            continue
        matched_k = _glued_compound_span(tokens, ti, spoken)
        if matched_k is None:
            return None
        ti += matched_k
        wi += 1
    return wi - 1


def segment_index_for_whisper_time(
    segments: list[dict[str, Any]], wall_time: float
) -> int:
    """Index of the Whisper segment whose ``start`` is last among those <= ``wall_time``.

    ``segments`` is the ``segments`` list from ``timing.json`` for one narration stem.
    """
    if not segments:
        return 0
    best_i = 0
    best_start = float("-inf")
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        try:
            s0 = float(seg.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        if s0 <= wall_time and s0 >= best_start:
            best_start = s0
            best_i = i
    return best_i


def wait_word_index_for_time(words: list[dict[str, Any]], wall_time: float) -> int:
    """Index of the Whisper **word** whose ``start`` is last among those ``<= wall_time``."""
    if not words:
        return 0
    best_i = 0
    best_start = float("-inf")
    for i, w in enumerate(words):
        if not isinstance(w, dict):
            continue
        try:
            s0 = float(w.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        if s0 <= wall_time and s0 >= best_start:
            best_start = s0
            best_i = i
    return best_i


def wait_word_index_at_segment_start(
    segments: list[dict[str, Any]], words: list[dict[str, Any]], segment_index: int
) -> int:
    """Map legacy ``wait_segment`` index → ``wait_word`` index at that segment's start."""
    if segment_index < 0 or segment_index >= len(segments):
        return 0
    try:
        t = float(segments[segment_index].get("start", 0.0))
    except (TypeError, ValueError):
        return 0
    return wait_word_index_for_time(words, t)


def _whisper_word_stream(
    words: list[dict[str, Any]],
) -> list[tuple[str, float, int]]:
    """``(normalized word, start, original index)`` for nonempty spoken tokens."""
    word_stream: list[tuple[str, float, int]] = []
    for wi, word in enumerate(words):
        if not isinstance(word, dict):
            continue
        normalized = _normalize_word(word.get("word", ""))
        if not normalized:
            continue
        try:
            start = float(word.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        word_stream.append((normalized, start, wi))
    return word_stream


def _find_label_in_stream(
    label: str,
    from_idx: int,
    word_stream: list[tuple[str, float, int]],
) -> tuple[int, int] | None:
    """Return (last matched stream index, original ``words`` index of phrase start)."""
    tokens = _label_tokens(label)
    if not tokens:
        return None
    norms = [item[0] for item in word_stream]
    i = from_idx
    while i < len(word_stream):
        last = _consume_label_tokens_at(tokens, norms, i)
        if last is not None:
            return (last, word_stream[i][2])
        i += 1
    return None


def _advance_past_label(
    label: str, cursor: int, word_stream: list[tuple[str, float, int]]
) -> int:
    found = _find_label_in_stream(label, cursor, word_stream)
    if found is None:
        return cursor
    return found[0] + 1


def _preserved_row_cursor(
    row: dict[str, Any],
    boxes: list[Any],
    cursor: int,
    word_stream: list[tuple[str, float, int]],
    overwrite: bool,
) -> int | None:
    """Cursor after a row whose pacing is left alone, or ``None`` to keep syncing."""
    if overwrite:
        return None
    if row.get("wait_word") is None and row.get("wait_segment") is None:
        return None
    first = boxes[0]
    if isinstance(first, dict):
        return _advance_past_label(str(first.get("label", "")), cursor, word_stream)
    return cursor


def _sync_one_box(
    box: Any,
    *,
    overwrite: bool,
    cursor: int,
    word_stream: list[tuple[str, float, int]],
) -> int:
    if not isinstance(box, dict):
        return cursor
    box.pop("wait_at", None)
    if box.get("image") is not None and not str(box.get("label", "")).strip():
        # Unlabeled image element: no transcript anchor to re-derive from,
        # so keep any author-provided wait_word as-is.
        return cursor
    if not overwrite and box.get("wait_word") is not None:
        return _advance_past_label(str(box.get("label", "")), cursor, word_stream)
    found = _find_label_in_stream(str(box.get("label", "")), cursor, word_stream)
    if found is not None:
        last_stream_i, first_word_i = found
        box["wait_word"] = int(first_word_i)
        box.pop("wait_segment", None)
        return last_stream_i + 1
    if overwrite:
        # Fail-closed: never keep a leftover LLM / legacy index for an
        # unmatched spoken label — callers must reject or set pace: none.
        box.pop("wait_word", None)
        box.pop("wait_segment", None)
    return cursor


def _sync_spec_rows(
    rows: list[Any],
    *,
    overwrite: bool,
    cursor: int,
    word_stream: list[tuple[str, float, int]],
) -> int:
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("wait_at", None)
        boxes = row.get("boxes")
        if not isinstance(boxes, list) or not boxes:
            continue
        preserved = _preserved_row_cursor(row, boxes, cursor, word_stream, overwrite)
        if preserved is not None:
            cursor = preserved
            continue
        if overwrite:
            row.pop("wait_word", None)
            row.pop("wait_segment", None)
        for box in boxes:
            cursor = _sync_one_box(
                box, overwrite=overwrite, cursor=cursor, word_stream=word_stream
            )
    return cursor


def _shallow_copy_rows(rows: list[Any]) -> list[Any]:
    return [dict(row) if isinstance(row, dict) else row for row in rows]


def _copy_one_page(page: Any, apply_rows: Any) -> Any:
    if not isinstance(page, dict):
        return page
    copied = dict(page)
    if isinstance(copied.get("rows"), list):
        copied["rows"] = _shallow_copy_rows(copied["rows"])
        apply_rows(copied["rows"])
    return copied


def _copy_spec_rows(spec: dict[str, Any], apply_rows: Any) -> dict[str, Any]:
    """Shallow-copy pages or rows, then let ``apply_rows`` mutate each row list."""
    out = dict(spec)
    if out.get("pages") is not None:
        out["pages"] = [_copy_one_page(page, apply_rows) for page in out["pages"]]
        return out
    if isinstance(out.get("rows"), list):
        out["rows"] = _shallow_copy_rows(out["rows"])
        apply_rows(out["rows"])
    return out


def sync_row_labels_to_whisper_words(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Set ``wait_word`` on each **box** from its ``label`` → first spoken match (in order).

    Matching is **fail-closed**: exact/stem token equality, hyphen/underscore splits,
    and glued Whisper compounds (label ``version-controlled`` ↔ spoken
    ``versioncontrolled``). No fuzzy containment and no leftover LLM ``wait_word``
    when the label is absent from the transcript. Each matched box waits at word
    ``start``. Row-level ``wait_word`` / ``wait_segment`` are cleared when
    ``overwrite=True``.
    """
    if not isinstance(words, list) or not words:
        return spec
    word_stream = _whisper_word_stream(words)
    if not word_stream:
        return spec
    cursor = {"n": 0}

    def _process_rows(rows: list[Any]) -> None:
        cursor["n"] = _sync_spec_rows(
            rows, overwrite=overwrite, cursor=cursor["n"], word_stream=word_stream
        )

    return _copy_spec_rows(spec, _process_rows)


def _pace_none(obj: dict[str, Any]) -> bool:
    return str(obj.get("pace", "")).strip().lower() == "none"


def _paced_anchor(
    box: Any, *, row_opt_out: bool, loc: str
) -> str | None:
    if not isinstance(box, dict) or row_opt_out or _pace_none(box):
        return None
    if _is_image_element(box) and not str(box.get("label", "")).strip():
        return None
    label = str(box.get("label", "")).strip()
    if not label:
        return None
    return f"{loc}: label {label!r}"


def _wait_word_issue(box: dict[str, Any], loc: str, *, words_present: bool) -> str | None:
    if not words_present or box.get("wait_word") is not None:
        return None
    return (
        f"{loc} has no wait_word match in "
        "timing.json words — use a spoken phrase from the narration, or set "
        "pace: none to opt out of beat sync"
    )


def _row_pacing_scan(
    spec: dict[str, Any],
    pi: int,
    ri: int,
    row: Any,
    *,
    words_present: bool,
    issues: list[str],
    paced_anchors: list[str],
) -> None:
    if not isinstance(row, dict):
        return
    boxes = row.get("boxes")
    if not isinstance(boxes, list):
        return
    prefix = f"pages[{pi}].rows[{ri}]" if spec.get("pages") is not None else f"rows[{ri}]"
    row_opt_out = _pace_none(row)
    for bi, box in enumerate(boxes):
        loc_base = f"{prefix}.boxes[{bi}]"
        anchor = _paced_anchor(box, row_opt_out=row_opt_out, loc=loc_base)
        if anchor is None:
            continue
        paced_anchors.append(anchor)
        issue = _wait_word_issue(box, anchor, words_present=words_present)
        if issue is not None:
            issues.append(issue)


def _missing_timing_words_issue(paced_anchors: list[str]) -> list[str]:
    shown = paced_anchors[0]
    more = f" (+{len(paced_anchors) - 1} more)" if len(paced_anchors) > 1 else ""
    return [
        f"{shown}{more} is paced but timing.json has no word-level `words` — "
        "run `docgen timestamps` before scene-compile, or set pace: none to opt "
        "out of beat sync"
    ]


def pacing_violations(spec: dict[str, Any], *, words_present: bool) -> list[str]:
    """Return issues when paced story boxes cannot bind to timing words.

    Unpaced cascading ``timed_play`` finishes the board early and freezes through
    the rest of the narration. Opt out per box/row with ``pace: none``.
    Unlabeled image elements are exempt (no spoken anchor).

    If any labeled story box is still paced, ``timing.json`` must have a nonempty
    ``words`` list (run ``docgen timestamps``). Missing words is not an implicit
    opt-out.
    """
    issues: list[str] = []
    paced_anchors: list[str] = []
    for pi, rows in enumerate(_spec_pages_rows(spec)):
        for ri, row in enumerate(rows):
            _row_pacing_scan(
                spec,
                pi,
                ri,
                row,
                words_present=words_present,
                issues=issues,
                paced_anchors=paced_anchors,
            )
    if paced_anchors and not words_present:
        return _missing_timing_words_issue(paced_anchors)
    return issues


def _anchor_time(box: Any, words: list[dict[str, Any]]) -> tuple[str, float] | None:
    if not isinstance(box, dict) or _pace_none(box):
        return None
    label = str(box.get("label", "")).strip()
    ww = box.get("wait_word")
    if not label or ww is None:
        return None
    try:
        wi = int(ww)
    except (TypeError, ValueError):
        return None
    if wi < 0 or wi >= len(words) or not isinstance(words[wi], dict):
        return None
    try:
        return (label, float(words[wi].get("start", 0.0)))
    except (TypeError, ValueError):
        return None


def iter_paced_label_anchors(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
) -> list[tuple[str, float]]:
    """Return ``(label, spoken_start)`` for paced boxes after fail-closed sync.

    Used by validate ``story_end`` and ``av_sync`` OCR anchoring.
    """
    if not isinstance(words, list) or not words:
        return []
    synced = sync_row_labels_to_whisper_words(spec, words, overwrite=True)
    out: list[tuple[str, float]] = []
    for rows in _spec_pages_rows(synced):
        for row in rows:
            if not isinstance(row, dict) or _pace_none(row):
                continue
            boxes = row.get("boxes")
            if not isinstance(boxes, list):
                continue
            for box in boxes:
                anchor = _anchor_time(box, words)
                if anchor is not None:
                    out.append(anchor)
    return out


def last_paced_reveal_time(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
) -> float | None:
    """Wall-clock ``start`` of the latest paced box reveal, or ``None`` if none.

    Re-derives ``wait_word`` from labels (fail-closed sync) then takes the maximum
    word ``start`` among boxes that are not ``pace: none``. Used by validate
    ``story_end`` to detect boards that finish long before the narration ends.
    """
    anchors = iter_paced_label_anchors(spec, words)
    if not anchors:
        return None
    return max(t for _, t in anchors)


@dataclass(frozen=True)
class RevealEvent:
    """One box reveal on the compiled ``_TimedScene`` clock timeline."""

    label: str
    page: int
    row: int
    box: int
    wait_word: int | None
    word_start: float | None
    effective_at: float
    wait_skipped: bool
    run_time: float
    page_fade_out: float
    emphasis: str = "none"
    dwell_run_time: float = 0.0
    reveal: str = "fade"
    hold_pulses: tuple[HoldPulse, ...] = ()


def default_box_reveal(
    box: dict[str, Any],
    *,
    page_has_edges: bool,
    is_first_on_page: bool,
) -> str:
    """``grow`` the first node of a flow page when the author omitted ``reveal``."""
    raw = box.get("reveal")
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower()
    if page_has_edges and is_first_on_page:
        return "grow"
    return "fade"


def _box_wait_word(row: dict[str, Any], box: dict[str, Any], box_index: int) -> int | None:
    if _pace_none(row) or _pace_none(box):
        return None
    ww = box.get("wait_word")
    if ww is None and box_index == 0:
        ww = row.get("wait_word")
    if ww is None:
        return None
    try:
        return int(ww)
    except (TypeError, ValueError):
        return None


def _word_start_at(words: list[dict[str, Any]], index: int | None) -> float | None:
    if index is None or not words or index < 0 or index >= len(words):
        return None
    w = words[index]
    if not isinstance(w, dict):
        return None
    try:
        start = float(w.get("start", 0.0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(start):
        return None
    return start


def _slot_label(box: dict[str, Any]) -> str:
    if box.get("image") is not None and not str(box.get("label", "")).strip():
        # Unlabeled image: still revealed, but no spoken wait.
        return ""
    return str(box.get("label", "")).strip()


def _reveal_slot(
    box: dict[str, Any],
    row: dict[str, Any],
    *,
    p: int,
    r: int,
    b: int,
    first_box_seen: bool,
    page_has_edges: bool,
    trans: Any,
    default_tr: str,
    default_tr_rt: float,
    row_rt: float,
    words: list[dict[str, Any]] | None,
    layout: Any,
) -> dict[str, Any]:
    ww = _box_wait_word(row, box, b)
    return {
        "page": p,
        "row": r,
        "box": b,
        "label": _slot_label(box),
        "wait_word": ww,
        "word_start": _word_start_at(words or [], ww),
        "run_time": row_rt,
        "page_transition": str(trans or default_tr),
        "page_transition_run_time": default_tr_rt,
        "emphasis": resolve_box_emphasis(box, layout),
        "reveal": default_box_reveal(
            box,
            page_has_edges=page_has_edges,
            is_first_on_page=not first_box_seen,
        ),
    }


def _row_run_time(row: dict[str, Any]) -> float:
    try:
        return float(row.get("run_time", 1.0))
    except (TypeError, ValueError):
        return 1.0


def _page_reveal_slots(
    page: dict[str, Any],
    rows: list[Any],
    *,
    p: int,
    default_tr: str,
    default_tr_rt: float,
    words: list[dict[str, Any]] | None,
    layout: Any,
) -> list[dict[str, Any]]:
    trans = page.get("transition", default_tr)
    page_has_edges = bool(page.get("edges"))
    first_box_seen = False
    slots: list[dict[str, Any]] = []
    for r, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        boxes = row.get("boxes")
        if not isinstance(boxes, list):
            continue
        row_rt = _row_run_time(row)
        for b, box in enumerate(boxes):
            if not isinstance(box, dict):
                continue
            slots.append(
                _reveal_slot(
                    box,
                    row,
                    p=p,
                    r=r,
                    b=b,
                    first_box_seen=first_box_seen,
                    page_has_edges=page_has_edges,
                    trans=trans,
                    default_tr=default_tr,
                    default_tr_rt=default_tr_rt,
                    row_rt=row_rt,
                    words=words,
                    layout=layout,
                )
            )
            first_box_seen = True
    return slots


def iter_reveal_slots(
    spec: dict[str, Any],
    words: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return paced/unpaced story boxes in compiled reveal order.

    Each slot is a dict with page/row/box indices, label, wait_word, word_start,
    row run_time, and page transition metadata for the first box of each page.
    When ``words`` is provided, ``wait_word`` is re-derived via fail-closed sync.
    """
    working = (
        sync_row_labels_to_whisper_words(spec, words, overwrite=True)
        if words
        else spec
    )
    layout = working.get("layout") or {}
    default_tr = str(layout.get("page_transition", "fade"))
    default_tr_rt = float(layout.get("page_transition_run_time", 0.45))
    slots: list[dict[str, Any]] = []
    for p, page in enumerate(_normalized_pages(working)):
        if not isinstance(page, dict):
            continue
        rows = page.get("rows")
        if not isinstance(rows, list):
            continue
        slots.extend(
            _page_reveal_slots(
                page,
                rows,
                p=p,
                default_tr=default_tr,
                default_tr_rt=default_tr_rt,
                words=words,
                layout=layout,
            )
        )
    return slots


def _clock_after_wait(
    clock: float, ww: Any, word_start: Any
) -> tuple[float, bool]:
    if ww is None or word_start is None:
        return clock, False
    target = float(word_start)
    if target > clock + 0.05:
        return target, False
    if clock > target + 0.05:
        # Truly late: prior FadeIn/title already passed this spoken start.
        return clock, True
    # On-time within tolerance (clamp landed on the beat).
    return max(clock, target), False


def _opening_page_fade(slot: dict[str, Any]) -> float:
    if int(slot["page"]) <= 0 or int(slot["row"]) != 0 or int(slot["box"]) != 0:
        return 0.0
    if str(slot["page_transition"]) not in ANIMATED_PAGE_TRANSITIONS:
        return 0.0
    return float(slot["page_transition_run_time"])


def _next_paced_start(slots: list[dict[str, Any]], index: int) -> float | None:
    for nxt in slots[index + 1 :]:
        if nxt["wait_word"] is not None and nxt["word_start"] is not None:
            return float(nxt["word_start"])
    return None


def _shrink_page_fade(page_fade_out: float, budget: float) -> float:
    if page_fade_out > 0 and page_fade_out > max(0.0, budget - MIN_REVEAL_RUN_TIME):
        return max(0.05, budget - MIN_REVEAL_RUN_TIME)
    return page_fade_out


def _clamp_slot_durations(
    rt: float,
    page_fade_out: float,
    clock: float,
    next_target: float | None,
    clamp_run_times: bool,
) -> tuple[float, float]:
    if not clamp_run_times or next_target is None:
        return rt, page_fade_out
    budget = next_target - clock
    if page_fade_out + rt > budget and budget > 0:
        # Prefer keeping a short FadeIn; shrink page fade first.
        page_fade_out = _shrink_page_fade(page_fade_out, budget)
        remain = next_target - (clock + page_fade_out)
        if remain < rt:
            rt = max(MIN_REVEAL_RUN_TIME, remain)
        return rt, page_fade_out
    if budget <= 0:
        page_fade_out = 0.05 if page_fade_out > 0 else 0.0
        rt = MIN_REVEAL_RUN_TIME
    return rt, page_fade_out


def _slot_hold(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
    slot: dict[str, Any],
    clock_after_reveal: float,
    next_target: float | None,
) -> tuple[tuple[HoldPulse, ...], float, str]:
    requested = str(slot.get("emphasis") or "none")
    default_dwell = float(
        (spec.get("layout") or {}).get("dwell_run_time", DEFAULT_DWELL_RUN_TIME)
    )
    deadline = next_target
    if deadline is None:
        tail = audio_end_from_words(words)
        if tail is not None and tail > clock_after_reveal:
            deadline = tail
    pulses = plan_hold_pulses(
        clock_after_reveal,
        deadline,
        requested=requested,
        default_rt=default_dwell,
    )
    dwell_rt = float(pulses[0].run_time) if pulses else 0.0
    emphasis = requested if dwell_rt > 0 else "none"
    return pulses, dwell_rt, emphasis


def _reveal_event(
    slot: dict[str, Any],
    *,
    clock: float,
    wait_skipped: bool,
    rt: float,
    page_fade_out: float,
    emphasis: str,
    dwell_rt: float,
    pulses: tuple[HoldPulse, ...],
) -> RevealEvent:
    return RevealEvent(
        label=str(slot["label"]),
        page=int(slot["page"]),
        row=int(slot["row"]),
        box=int(slot["box"]),
        wait_word=slot["wait_word"],
        word_start=slot["word_start"],
        effective_at=float(clock),
        wait_skipped=wait_skipped,
        run_time=float(rt),
        page_fade_out=float(page_fade_out),
        emphasis=emphasis,
        dwell_run_time=float(dwell_rt),
        reveal=str(slot.get("reveal") or "fade"),
        hold_pulses=pulses,
    )


def simulate_reveal_timeline(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
    *,
    title_run_time: float = TITLE_WRITE_RUN_TIME,
    clamp_run_times: bool = True,
) -> list[RevealEvent]:
    """Simulate ``_TimedScene`` clock for compiled wait_word + FadeIn sequences.

    When ``clamp_run_times`` is True (compile default), FadeIn / page FadeOut
    durations shrink so ``_clock`` cannot pass the next paced word start — the
    bug that dumped the first board then froze while narration continued.
    """
    slots = iter_reveal_slots(spec, words)
    if not slots:
        return []

    first_start = next(
        (float(s["word_start"]) for s in slots if s["word_start"] is not None),
        None,
    )
    if clamp_run_times:
        title_run_time = clamp_title_run_time(title_run_time, first_start)
    clock = float(title_run_time)
    events: list[RevealEvent] = []

    for i, slot in enumerate(slots):
        clock, wait_skipped = _clock_after_wait(clock, slot["wait_word"], slot["word_start"])
        page_fade_out = _opening_page_fade(slot)
        next_target = _next_paced_start(slots, i)
        rt, page_fade_out = _clamp_slot_durations(
            float(slot["run_time"]), page_fade_out, clock, next_target, clamp_run_times
        )
        if page_fade_out > 0:
            clock += page_fade_out
        clock_after_reveal = clock + rt
        pulses, dwell_rt, emphasis = _slot_hold(
            spec, words, slot, clock_after_reveal, next_target
        )
        events.append(
            _reveal_event(
                slot,
                clock=clock,
                wait_skipped=wait_skipped,
                rt=rt,
                page_fade_out=page_fade_out,
                emphasis=emphasis,
                dwell_rt=dwell_rt,
                pulses=pulses,
            )
        )
        clock = clock_after_reveal + hold_span_seconds(pulses)

    return events


def _skip_ratio_issue(
    paced: list[RevealEvent], max_skip_ratio: float
) -> str | None:
    skipped = sum(1 for event in paced if event.wait_skipped)
    skip_ratio = skipped / len(paced)
    if skip_ratio > max_skip_ratio and skipped >= 2:
        return (
            f"wait_until_word no-op ratio {skip_ratio:.0%} ({skipped}/{len(paced)}) "
            f"exceeds max_skip_ratio={max_skip_ratio:.0%} — FadeIn/title run_time "
            "pushed _clock past spoken word starts (first board dumps, then freezes)"
        )
    return None


def _skip_streak(paced: list[RevealEvent]) -> int:
    streak = 0
    best = 0
    for event in paced:
        if event.wait_skipped:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def _early_idle_issue(
    events: list[RevealEvent],
    audio_end: float,
    max_early_sec: float,
    max_early_ratio: float,
) -> str | None:
    last_effective = max(
        event.effective_at + event.run_time + hold_span_seconds(event.hold_pulses or ())
        for event in events
    )
    early_idle = audio_end - last_effective
    early_ratio = early_idle / audio_end if audio_end > 0 else 0.0
    if early_idle > max_early_sec and early_ratio > max_early_ratio:
        return (
            f"effective last reveal at {last_effective:.2f}s leaves "
            f"early_idle={early_idle:.2f}s ({early_ratio:.0%} of audio_end="
            f"{audio_end:.2f}s) — visual story finished on the Manim clock long "
            "before narration ends"
        )
    return None


def reveal_cadence_violations(
    events: list[RevealEvent],
    *,
    audio_end: float,
    max_skip_ratio: float = 0.25,
    max_consecutive_skips: int = 2,
    max_early_sec: float = 40.0,
    max_early_ratio: float = 0.45,
) -> list[str]:
    """Return issues when the simulated clock dumps boxes then idles.

    Checks (issue #66):

    * too many ``wait_until_word`` no-ops (``_clock`` already past word start)
    * long consecutive skip streaks (rapid cascade)
    * last **effective** reveal finishes far before ``audio_end`` (metadata-only
      ``story_end`` misses this when Whisper starts look late but Manim raced)
    """
    if not events or audio_end <= 0:
        return []

    issues: list[str] = []
    paced = [event for event in events if event.wait_word is not None]
    if paced:
        ratio_issue = _skip_ratio_issue(paced, max_skip_ratio)
        if ratio_issue is not None:
            issues.append(ratio_issue)
        best = _skip_streak(paced)
        if best > max_consecutive_skips:
            issues.append(
                f"{best} consecutive skipped waits (max_consecutive_skips="
                f"{max_consecutive_skips}) — boxes cascade with only FadeIn gaps"
            )
    early = _early_idle_issue(events, audio_end, max_early_sec, max_early_ratio)
    if early is not None:
        issues.append(early)
    return issues


def _upgrade_row_wait_segment(
    row: Any, words: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> None:
    if not isinstance(row, dict):
        return
    ws = row.get("wait_segment")
    if ws is None:
        return
    boxes = row.get("boxes")
    if not isinstance(boxes, list) or not boxes or not isinstance(boxes[0], dict):
        row.pop("wait_segment", None)
        return
    if boxes[0].get("wait_word") is None:
        boxes[0]["wait_word"] = wait_word_index_at_segment_start(segments, words, int(ws))
    row.pop("wait_segment", None)


def upgrade_wait_segments_to_wait_words(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Turn legacy ``wait_segment`` on a row into the **first box**'s ``wait_word`` (when possible)."""
    if not words or not segments:
        return spec

    def _rows(rs: list[Any]) -> None:
        for row in rs:
            _upgrade_row_wait_segment(row, words, segments)

    return _copy_spec_rows(spec, _rows)


def spec_has_wait_segment(spec: dict[str, Any]) -> bool:
    """True if any row or box still carries legacy ``wait_segment``."""
    for rows in _spec_pages_rows(spec):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("wait_segment") is not None:
                return True
            for box in row.get("boxes") or []:
                if isinstance(box, dict) and box.get("wait_segment") is not None:
                    return True
    return False


def _flat_spec_rows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rows in _spec_pages_rows(spec):
        for row in rows:
            if isinstance(row, dict):
                out.append(row)
    return out


def _overlay_row_wait_words(dst: dict[str, Any], src: dict[str, Any]) -> None:
    dst.pop("wait_segment", None)
    dst.pop("wait_word", None)
    sboxes = src.get("boxes") or []
    dboxes = dst.get("boxes") or []
    for db, sb in zip(dboxes, sboxes):
        if not isinstance(db, dict) or not isinstance(sb, dict):
            continue
        db.pop("wait_segment", None)
        ww = sb.get("wait_word")
        if ww is None:
            db.pop("wait_word", None)
        else:
            db["wait_word"] = int(ww)


def disk_spec_with_merged_wait_words(
    original: dict[str, Any],
    merged: dict[str, Any],
) -> dict[str, Any]:
    """Copy compiled ``wait_word`` pacing onto the authored spec; drop ``wait_segment``."""
    out = copy.deepcopy(original)
    src_rows = _flat_spec_rows(merged)
    dst_rows = _flat_spec_rows(out)
    if len(src_rows) != len(dst_rows):
        return out
    for dst, src in zip(dst_rows, src_rows):
        _overlay_row_wait_words(dst, src)
    if "timing_key" not in original:
        out.pop("timing_key", None)
    return out


def _row_references_whisper_wait(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("wait_word") is not None or row.get("wait_segment") is not None:
        return True
    for box in row.get("boxes") or []:
        if isinstance(box, dict) and (
            box.get("wait_word") is not None or box.get("wait_segment") is not None
        ):
            return True
    return False


def spec_rows_reference_whisper_waits(spec: dict[str, Any]) -> bool:
    """True if any row or box references Whisper pacing (needs timing enrichment)."""
    for rows in _spec_pages_rows(spec):
        for row in rows:
            if _row_references_whisper_wait(row):
                return True
    return False


def _coerce_row_wait_at(row: Any, words: list[dict[str, Any]]) -> None:
    if not isinstance(row, dict) or row.get("wait_at") is None:
        return
    t = float(row["wait_at"])
    boxes = row.get("boxes")
    if isinstance(words, list) and words and isinstance(boxes, list) and boxes:
        if isinstance(boxes[0], dict):
            boxes[0]["wait_word"] = wait_word_index_for_time(words, t)
    row.pop("wait_at", None)


def coerce_legacy_wait_at_to_whisper_rows(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace legacy ``wait_at`` with ``wait_word`` when ``words`` exist; otherwise drop ``wait_at``."""
    _ = segments

    def _apply_rows(rs: list[Any]) -> None:
        for row in rs:
            _coerce_row_wait_at(row, words)

    return _copy_spec_rows(spec, _apply_rows)


def sanitize_pacing_conflicts(spec: dict[str, Any]) -> dict[str, Any]:
    """Prefer box-level ``wait_word`` when a row also has row-level pacing (LLM drafts)."""

    def _fix_rows(rows: list[Any]) -> list[Any]:
        out: list[Any] = []
        for row in rows:
            if not isinstance(row, dict):
                out.append(row)
                continue
            nr = dict(row)
            boxes = nr.get("boxes")
            if isinstance(boxes, list):
                box_pacing = any(
                    isinstance(b, dict)
                    and (b.get("wait_word") is not None or b.get("wait_segment") is not None)
                    for b in boxes
                )
                if box_pacing:
                    nr.pop("wait_word", None)
                    nr.pop("wait_segment", None)
            out.append(nr)
        return out

    out = dict(spec)
    if out.get("pages") is not None:
        new_pages: list[Any] = []
        for page in out["pages"]:
            if not isinstance(page, dict):
                new_pages.append(page)
                continue
            p = dict(page)
            if isinstance(p.get("rows"), list):
                p["rows"] = _fix_rows(p["rows"])
            new_pages.append(p)
        out["pages"] = new_pages
    elif isinstance(out.get("rows"), list):
        out["rows"] = _fix_rows(out["rows"])
    return out


# Light stopword list for subject-beat clustering / label coverage (not NLP-grade).
_CONTENT_STOPWORDS = frozenset(
    """
    a an the and or but if then else when while for from into onto with without
    this that these those it its they them their we our you your he she his her
    is are was were be been being do does did done have has had having will would
    can could should may might must shall of to in on at by as so not no nor
    also just only very more most such than then there here about into over under
    up down out off again further once each every both few other some any all
    """.split()
)


def count_spec_labels(spec: dict[str, Any]) -> int:
    """Count labeled boxes / image elements across ``pages`` or ``rows``."""
    return len(list_spec_labels(spec))


def list_spec_labels(spec: dict[str, Any]) -> list[str]:
    """Return non-empty box/image labels in page order."""
    out: list[str] = []
    pages = _spec_pages_rows(spec)
    for rows in pages:
        for row in rows:
            if not isinstance(row, dict):
                continue
            boxes = row.get("boxes")
            if not isinstance(boxes, list):
                continue
            for box in boxes:
                if not isinstance(box, dict):
                    continue
                label = str(box.get("label", "")).strip()
                if label:
                    out.append(label)
                elif str(box.get("image", "")).strip():
                    # Image-only: use stem as a weak anchor for coverage checks.
                    stem = Path(str(box["image"])).stem.replace("-", " ").replace("_", " ")
                    if stem.strip():
                        out.append(stem.strip())
    return out


def narration_sentences(narration_text: str) -> list[str]:
    """Split narration markdown into spoken sentences (heading-stripped)."""
    text = re.sub(r"(?m)^#.*$", " ", narration_text or "")
    text = re.sub(r"[`*_>#]", " ", text)
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        for sent in _SENTENCE_SPLIT_RE.split(para):
            s = sent.strip()
            if s:
                out.append(s)
    return out


def narration_sentence_count(narration_text: str) -> int:
    """Count spoken sentences in narration markdown."""
    return len(narration_sentences(narration_text))


def content_tokens(text: str) -> set[str]:
    """Content tokens for beat clustering / label↔narration coverage."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 2 and w not in _CONTENT_STOPWORDS}


def _glue_tokens(per_sent: list[set[str]]) -> set[str]:
    """Document-frequent tokens are weak merge signals (appear in many sentences)."""
    df: dict[str, int] = {}
    for toks in per_sent:
        for word in toks:
            df[word] = df.get(word, 0) + 1
    n = len(per_sent)
    return {word for word, count in df.items() if count >= max(3, (n + 1) // 2)}


def _continues_subject(
    toks: set[str],
    prev_toks: set[str],
    glue: set[str],
    jaccard_threshold: float,
) -> bool:
    if not toks or not prev_toks:
        return False
    shared = (toks & prev_toks) - glue
    union = (toks | prev_toks) - glue
    jacc = (len(shared) / len(union)) if union else 0.0
    return bool(shared or jacc >= jaccard_threshold)


def cluster_subject_beats(
    sentences: list[str],
    *,
    jaccard_threshold: float = 0.25,
) -> list[str]:
    """Merge consecutive sentences that continue the same subject into beats.

    Overlap is measured against the **previous sentence only** (not the whole
    accumulated beat) so a shared domain word like ``pipeline`` across distant
    topics does not glue unrelated beats. Several sentences may elaborate one
    on-screen idea; a sharp topic shift starts a new beat that needs its own label.
    """
    if not sentences:
        return []
    per_sent = [content_tokens(s) for s in sentences]
    glue = _glue_tokens(per_sent)
    beats: list[list[str]] = []
    for i, sent in enumerate(sentences):
        continues = bool(beats) and _continues_subject(
            per_sent[i], per_sent[i - 1] if i else set(), glue, jaccard_threshold
        )
        if continues:
            beats[-1].append(sent)
        else:
            beats.append([sent])
    return [" ".join(group) for group in beats]


def label_covers_beat(label: str, beat_text: str) -> bool:
    """True when a label's content tokens substantially appear in the beat text."""
    lt = content_tokens(label)
    bt = content_tokens(beat_text)
    if not lt or not bt:
        return False
    shared = lt & bt
    if not shared:
        return False
    # Short labels: any shared content word. Longer: majority of label tokens.
    need = 1 if len(lt) <= 2 else max(1, (len(lt) + 1) // 2)
    return len(shared) >= need


def min_labels_for_narration(narration_text: str, *, word_count: int = 0) -> int:
    """Soft prompt hint: number of subject beats (not a hard label quota).

    ``word_count`` is accepted for API compatibility; coverage uses beats, not words.
    """
    del word_count  # coverage gate does not use blind word quotas
    beats = cluster_subject_beats(narration_sentences(narration_text))
    return len(beats)


def _uncovered_beat_lines(beats: list[str], labels: list[str]) -> list[str]:
    uncovered: list[str] = []
    for i, beat in enumerate(beats, start=1):
        if any(label_covers_beat(lab, beat) for lab in labels):
            continue
        preview = beat if len(beat) <= 72 else beat[:69] + "..."
        uncovered.append(f"beat {i}: {preview}")
    return uncovered


def _coverage_issue(uncovered: list[str], beats: list[str], slack: int) -> str | None:
    allowed_uncovered = max(0, slack)
    if len(uncovered) <= allowed_uncovered:
        return None
    shown = "; ".join(uncovered[:5])
    more = f" (+{len(uncovered) - 5} more)" if len(uncovered) > 5 else ""
    note = (
        f" ({len(uncovered)} uncovered; allow ≤{allowed_uncovered} after retry)"
        if slack
        else f" ({len(uncovered)} of {len(beats)} beats uncovered)"
    )
    return (
        f"subject-beat coverage failed{note}: {shown}{more}. "
        "Add a spoken-phrase label for each new topic; keep the same board while "
        "sentences elaborate the same subject."
    )


def _invented_label_issue(labels: list[str], narration_text: str) -> str | None:
    narr_toks = content_tokens(narration_text)
    invented = [
        lab
        for lab in labels
        if content_tokens(lab) and not (content_tokens(lab) & narr_toks)
    ]
    if not invented:
        return None
    sample = ", ".join(repr(x) for x in invented[:6])
    more = f" (+{len(invented) - 6} more)" if len(invented) > 6 else ""
    return f"labels not spoken in narration (invented diagram terms): {sample}{more}"


def layout_density_violations(
    spec: dict[str, Any],
    *,
    narration_text: str,
    word_count: int = 0,
    slack: int = 0,
) -> list[str]:
    """Reject specs that miss subject beats or invent unspoken labels.

    This is **coverage**, not a blind label count: holding one board across several
    sentences in the same beat is fine; changing topic without a spoken-phrase
    label for that beat is not. ``slack`` is how many beats may remain uncovered
    after an LLM retry (near-miss).
    """
    del word_count
    sentences = narration_sentences(narration_text)
    if not sentences:
        return []
    beats = cluster_subject_beats(sentences)
    labels = list_spec_labels(spec)
    issues: list[str] = []
    coverage = _coverage_issue(_uncovered_beat_lines(beats, labels), beats, slack)
    if coverage is not None:
        issues.append(coverage)
    invented = _invented_label_issue(labels, narration_text)
    if invented is not None:
        issues.append(invented)
    return issues


def _positive_dims(boxes: list[Any], key: str) -> list[float] | None:
    try:
        vals = [float(box[key]) for box in boxes if isinstance(box, dict)]
    except (KeyError, TypeError, ValueError):
        return None
    if not vals:
        return None
    return vals


def _row_extents(row: Any, col_gap: float) -> tuple[float, float] | None:
    if not isinstance(row, dict):
        return None
    boxes = row.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        return None
    heights = _positive_dims(boxes, "height")
    widths = _positive_dims(boxes, "width")
    if not heights or not widths:
        return None
    width = sum(widths)
    if len(widths) > 1:
        width += col_gap * (len(widths) - 1)
    return max(heights), width


def _page_budget_issues(
    pi: int,
    rows: list[Any],
    *,
    budget: float,
    row_gap: float,
    col_gap: float,
) -> list[str]:
    row_heights: list[float] = []
    row_widths: list[float] = []
    for row in rows:
        extents = _row_extents(row, col_gap)
        if extents is None:
            continue
        height, width = extents
        row_heights.append(height)
        row_widths.append(width)
    stack_h = (
        sum(row_heights) + (len(row_heights) - 1) * row_gap if row_heights else 0.0
    )
    max_rw = max(row_widths) if row_widths else 0.0
    issues: list[str] = []
    if stack_h > budget + 0.02:
        issues.append(
            f"pages[{pi}] vertical stack ~{stack_h:.2f} exceeds frame budget ~{budget:.2f} "
            f"(split into more pages, reduce box height, or lower row_gap)"
        )
    if max_rw > _LAYOUT_HORIZONTAL_SAFE + 0.05:
        issues.append(
            f"pages[{pi}] widest row ~{max_rw:.2f} exceeds safe width ~{_LAYOUT_HORIZONTAL_SAFE:.2f} "
            f"(narrow boxes or use more rows)"
        )
    return issues


def layout_budget_violations(spec: dict[str, Any]) -> list[str]:
    """Return human-readable layout problems if a spec likely overflows the Manim frame.

    Used by ``docgen scene-spec-generate`` so LLM output is rejected before compile; hand-authored
    ``scene-compile`` does **not** call this (legacy specs may intentionally push limits).
    """
    title = spec.get("title")
    if not isinstance(title, dict):
        return []
    layout = spec.get("layout")
    if not isinstance(layout, dict):
        layout = {}
    try:
        budget = layout_stack_budget(title, layout)
    except (TypeError, ValueError):
        return []
    row_gap = float(layout.get("row_gap", 0.6))
    col_gap = float(layout.get("column_gap", 0.8))
    issues: list[str] = []
    for pi, rows in enumerate(_spec_pages_rows(spec)):
        issues.extend(
            _page_budget_issues(pi, rows, budget=budget, row_gap=row_gap, col_gap=col_gap)
        )
    issues.extend(layout_overlap_violations(spec))
    return issues


def _layout_gap_issues(row_gap: float, col_gap: float, title_buff: float) -> list[str]:
    issues: list[str] = []
    if title_buff + 1e-9 < MIN_TITLE_ROW_BUFF:
        issues.append(
            f"overlap: first_row_title_buff={title_buff:.2f} < {MIN_TITLE_ROW_BUFF} "
            "(first row will sit on the title band)"
        )
    if row_gap + 1e-9 < MIN_ROW_GAP:
        issues.append(
            f"overlap: row_gap={row_gap:.2f} < {MIN_ROW_GAP} (rows will collide)"
        )
    if col_gap + 1e-9 < MIN_COLUMN_GAP:
        issues.append(
            f"overlap: column_gap={col_gap:.2f} < {MIN_COLUMN_GAP} (boxes in a row will collide)"
        )
    return issues


def _dict_boxes(row: Any) -> list[dict[str, Any]] | None:
    if not isinstance(row, dict):
        return None
    boxes = [box for box in (row.get("boxes") or []) if isinstance(box, dict)]
    if not boxes:
        return None
    return boxes


def _row_boxes_dims(
    row: Any,
) -> tuple[list[dict[str, Any]], list[float], list[float]] | None:
    boxes = _dict_boxes(row)
    if boxes is None:
        return None
    try:
        heights = [float(box.get("height", 0)) for box in boxes]
        widths = [float(box.get("width", 0)) for box in boxes]
    except (TypeError, ValueError):
        return None
    if not heights or not widths:
        return None
    return boxes, heights, widths


def _box_clip_issues(
    lab: str,
    pi: int,
    *,
    left: float,
    right: float,
    bottom: float,
    top: float,
    title_bottom: float,
    frame_left: float,
    frame_right: float,
    frame_bottom: float,
) -> list[str]:
    issues: list[str] = []
    if top > title_bottom + 0.02:
        issues.append(f"overlap: {lab!r} on pages[{pi}] intersects the title band")
    if left < frame_left - 0.05 or right > frame_right + 0.05:
        issues.append(f"overlap: {lab!r} on pages[{pi}] clips the horizontal safe frame")
    if bottom < frame_bottom - 0.05:
        issues.append(f"overlap: {lab!r} on pages[{pi}] clips below the safe bottom")
    return issues


def _place_row_boxes(
    boxes: list[dict[str, Any]],
    heights: list[float],
    widths: list[float],
    *,
    pi: int,
    ri: int,
    y_top: float,
    col_gap: float,
    title_bottom: float,
    frame_left: float,
    frame_right: float,
    frame_bottom: float,
) -> tuple[list[str], list[tuple[float, float, float, float, str]]]:
    row_h = max(heights)
    row_w = sum(widths) + max(0, len(widths) - 1) * col_gap
    x = -row_w / 2.0
    issues: list[str] = []
    rects: list[tuple[float, float, float, float, str]] = []
    for bi, box in enumerate(boxes):
        w = widths[bi]
        h = heights[bi]
        # VGroup.arrange(RIGHT) centers on the row's vertical mid-line.
        mid_y = y_top - row_h / 2.0
        left, right = x, x + w
        bottom, top = mid_y - h / 2.0, mid_y + h / 2.0
        lab = str(box.get("label") or f"pages[{pi}].rows[{ri}].boxes[{bi}]")
        issues.extend(
            _box_clip_issues(
                lab,
                pi,
                left=left,
                right=right,
                bottom=bottom,
                top=top,
                title_bottom=title_bottom,
                frame_left=frame_left,
                frame_right=frame_right,
                frame_bottom=frame_bottom,
            )
        )
        rects.append((left, bottom, right, top, lab))
        x += w + col_gap
    return issues, rects


def _rect_pair_issues(
    rects: list[tuple[float, float, float, float, str]], pi: int
) -> list[str]:
    issues: list[str] = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            overlaps = (
                a[0] < b[2] - 0.02
                and b[0] < a[2] - 0.02
                and a[1] < b[3] - 0.02
                and b[1] < a[3] - 0.02
            )
            if overlaps:
                issues.append(f"overlap: {a[4]!r} intersects {b[4]!r} on pages[{pi}]")
    return issues


def _scan_overlap_page(
    pi: int,
    rows: list[Any],
    *,
    y_start: float,
    row_gap: float,
    col_gap: float,
    title_bottom: float,
    frame_left: float,
    frame_right: float,
    frame_bottom: float,
) -> list[str]:
    issues: list[str] = []
    y_top = y_start
    rects: list[tuple[float, float, float, float, str]] = []
    for ri, row in enumerate(rows):
        dims = _row_boxes_dims(row)
        if dims is None:
            continue
        boxes, heights, widths = dims
        row_issues, row_rects = _place_row_boxes(
            boxes,
            heights,
            widths,
            pi=pi,
            ri=ri,
            y_top=y_top,
            col_gap=col_gap,
            title_bottom=title_bottom,
            frame_left=frame_left,
            frame_right=frame_right,
            frame_bottom=frame_bottom,
        )
        issues.extend(row_issues)
        rects.extend(row_rects)
        y_top -= max(heights) + row_gap
    issues.extend(_rect_pair_issues(rects, pi))
    return issues


def layout_overlap_violations(spec: dict[str, Any]) -> list[str]:
    """Offline geometry: title collision, tight gaps, and boxes that clip the frame.

    Uses the same stack math as compile (no Manim). Catches the overlap cases
    OCR layout checks only see after a wasted render.
    """
    title = spec.get("title") if isinstance(spec.get("title"), dict) else {}
    layout = spec.get("layout") if isinstance(spec.get("layout"), dict) else {}
    try:
        row_gap = float(layout.get("row_gap", 0.6))
        col_gap = float(layout.get("column_gap", 0.8))
        title_buff = float(layout.get("first_row_title_buff", 0.5))
    except (TypeError, ValueError):
        return []
    issues = _layout_gap_issues(row_gap, col_gap, title_buff)
    fs = title.get("font_size")
    if not _is_yaml_number(fs):
        fs = 36
    has_sub = bool(str(title.get("subtitle") or "").strip())
    band = _title_band_estimate(int(fs), has_subtitle=has_sub)
    title_bottom = FRAME_HEIGHT / 2.0 - band
    for pi, rows in enumerate(_spec_pages_rows(spec)):
        issues.extend(
            _scan_overlap_page(
                pi,
                rows,
                y_start=title_bottom - title_buff,
                row_gap=row_gap,
                col_gap=col_gap,
                title_bottom=title_bottom,
                frame_left=-_LAYOUT_HORIZONTAL_SAFE / 2.0,
                frame_right=_LAYOUT_HORIZONTAL_SAFE / 2.0,
                frame_bottom=-FRAME_HEIGHT / 2.0 + _LAYOUT_BOTTOM_MARGIN,
            )
        )
    return issues


class SceneSpecError(ValueError):
    """Invalid scene spec (schema or semantic)."""


def load_scene_spec(path: Path) -> dict[str, Any]:
    """Load and validate a ``*.scene.yaml`` file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SceneSpecError(f"{path}: root must be a mapping")
    data = sanitize_pacing_conflicts(data)
    validate_scene_spec(data, path_label=str(path))
    return data


def _is_image_element(box: Any) -> bool:
    """True when a ``boxes`` entry is an **image element** (``image:`` key) instead of a labeled box."""
    return isinstance(box, dict) and box.get("image") is not None


def _require_positive_number(box: dict[str, Any], fld: str, bp: str) -> None:
    if fld not in box:
        raise SceneSpecError(f"{bp}: missing {fld}")
    value = box[fld]
    if not _is_yaml_number(value) or value <= 0:
        raise SceneSpecError(f"{bp}: {fld} must be a positive number")


def _validate_image_path(img: Any, bp: str) -> None:
    if not isinstance(img, str) or not img.strip():
        raise SceneSpecError(f"{bp}: image must be a non-empty bundle-relative path string")
    path = Path(img.strip())
    if path.is_absolute() or ".." in path.parts:
        raise SceneSpecError(
            f"{bp}: image path must be relative to the bundle directory (no absolute paths or '..')"
        )


def _reject_image_label_fields(box: dict[str, Any], bp: str) -> None:
    for fld in ("color", "font_size"):
        if fld in box:
            raise SceneSpecError(
                f"{bp}: {fld} is not allowed on an image element (only label boxes take {fld})"
            )


def _validate_image_prompt_and_label(box: dict[str, Any], bp: str) -> None:
    prompt = box.get("prompt")
    if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
        raise SceneSpecError(f"{bp}: prompt must be a non-empty string if set")
    lab = box.get("label")
    if lab is not None and not isinstance(lab, str):
        raise SceneSpecError(f"{bp}: label must be a string if set (used as timing anchor only)")


def _validate_image_element(box: dict[str, Any], *, bp: str) -> None:
    _validate_image_path(box.get("image"), bp)
    for fld in ("width", "height"):
        _require_positive_number(box, fld, bp)
    _reject_image_label_fields(box, bp)
    _validate_image_prompt_and_label(box, bp)


def _validate_pace_field(obj: dict[str, Any], *, path: str) -> None:
    if "pace" not in obj or obj.get("pace") is None:
        return
    val = str(obj.get("pace")).strip().lower()
    if val != "none":
        raise SceneSpecError(f"{path}: pace must be 'none' if set (opt out of beat sync)")


def _require_nonneg_int(value: Any, rp: str, fld: str) -> None:
    if value is None:
        return
    if not _is_yaml_int(value) or value < 0:
        raise SceneSpecError(f"{rp}: {fld} must be a non-negative int or null")


def _validate_row_run_time(row: dict[str, Any], rp: str) -> None:
    if "run_time" not in row:
        raise SceneSpecError(f"{rp}: run_time is required")
    rt = row["run_time"]
    if not _is_yaml_number(rt) or rt <= 0:
        raise SceneSpecError(f"{rp}: run_time must be a positive number")


def _validate_row_waits(row: dict[str, Any], rp: str) -> None:
    ws = row.get("wait_segment")
    ww = row.get("wait_word")
    _require_nonneg_int(ws, rp, "wait_segment")
    _require_nonneg_int(ww, rp, "wait_word")
    if ws is not None and ww is not None:
        raise SceneSpecError(
            f"{rp}: set at most one of wait_segment and wait_word (prefer wait_word for word timestamps)"
        )
    if row.get("wait_at") is not None:
        raise SceneSpecError(
            f"{rp}: wait_at is not allowed — use wait_word (``timing.json`` ``words`` index); "
            f"re-run `docgen scene-compile` after `docgen timestamps`."
        )


def _validate_box_wait(box: dict[str, Any], bp: str) -> bool:
    _validate_pace_field(box, path=bp)
    if box.get("wait_segment") is not None:
        raise SceneSpecError(
            f"{bp}: wait_segment on a box is not supported — use ``wait_word`` on the box, "
            f"or ``wait_segment`` on the row for legacy upgrade."
        )
    bww = box.get("wait_word")
    _require_nonneg_int(bww, bp, "wait_word")
    return bww is not None


def _validate_label_box_fields(box: dict[str, Any], bp: str) -> None:
    for fld in ("label", "color", "width", "height", "font_size"):
        if fld not in box:
            raise SceneSpecError(f"{bp}: missing {fld}")
    if str(box["color"]) not in ALLOWED_COLORS:
        raise SceneSpecError(f"{bp}: color must be one of {sorted(ALLOWED_COLORS)}")
    for num_f in ("width", "height", "font_size"):
        value = box[num_f]
        if not _is_yaml_number(value) or value <= 0:
            raise SceneSpecError(f"{bp}: {num_f} must be a positive number")


def _validate_box_subtitle(box: dict[str, Any], bp: str) -> None:
    bsub = box.get("subtitle")
    if bsub is None:
        return
    if not isinstance(bsub, str):
        raise SceneSpecError(f"{bp}: subtitle must be a string if set")
    if len(bsub.strip()) > 60:
        raise SceneSpecError(f"{bp}: subtitle must be at most 60 characters")


def _validate_choice(box: dict[str, Any], key: str, allowed: frozenset[str] | set[str], bp: str) -> None:
    value = box.get(key)
    if value is not None and str(value).strip().lower() not in allowed:
        raise SceneSpecError(f"{bp}: {key} must be one of {sorted(allowed)} if set")


def _validate_story_box(box: dict[str, Any], bp: str) -> None:
    _validate_label_box_fields(box, bp)
    _validate_box_subtitle(box, bp)
    _validate_choice(box, "shape", ALLOWED_SHAPES, bp)
    _validate_choice(box, "reveal", ALLOWED_REVEALS, bp)
    _validate_choice(box, "emphasis", ALLOWED_EMPHASIS, bp)


def _validate_one_box(box: Any, bp: str) -> bool:
    if not isinstance(box, dict):
        raise SceneSpecError(f"{bp}: box must be a mapping")
    paced = _validate_box_wait(box, bp)
    if _is_image_element(box):
        _validate_image_element(box, bp=bp)
        return paced
    _validate_story_box(box, bp)
    return paced


def _validate_one_row(row: Any, rp: str) -> None:
    if not isinstance(row, dict):
        raise SceneSpecError(f"{rp}: row must be a mapping")
    if "boxes" not in row:
        raise SceneSpecError(f"{rp}: missing boxes")
    boxes = row["boxes"]
    if not isinstance(boxes, list) or not boxes:
        raise SceneSpecError(f"{rp}: boxes must be a non-empty list")
    _validate_row_run_time(row, rp)
    _validate_pace_field(row, path=rp)
    _validate_row_waits(row, rp)
    box_pacing = False
    for j, box in enumerate(boxes):
        if _validate_one_box(box, f"{rp}: boxes[{j}]"):
            box_pacing = True
    has_row_pacing = row.get("wait_word") is not None or row.get("wait_segment") is not None
    if has_row_pacing and box_pacing:
        raise SceneSpecError(
            f"{rp}: set pacing on the row (``wait_word`` / ``wait_segment``) "
            f"**or** on boxes (``wait_word`` per box), not both"
        )


def _validate_row_list(rows: list[Any], *, path_label: str, prefix: str) -> None:
    for i, row in enumerate(rows):
        _validate_one_row(row, f"{path_label}: {prefix}[{i}]")


def _page_box_labels(rows: list[Any]) -> dict[str, int]:
    """Map box label → occurrence count on a page (labeled boxes only)."""
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for box in row.get("boxes") or []:
            if not isinstance(box, dict) or _is_image_element(box):
                continue
            lab = str(box.get("label", "")).strip()
            if lab:
                counts[lab] = counts.get(lab, 0) + 1
    return counts


def _validate_edge_ends(edge: dict[str, Any], ep: str, labels: dict[str, int]) -> None:
    for fld in ("from", "to"):
        if fld not in edge or not str(edge[fld]).strip():
            raise SceneSpecError(f"{ep}: {fld} is required (box label on this page)")
    src = str(edge["from"]).strip()
    dst = str(edge["to"]).strip()
    if src not in labels:
        raise SceneSpecError(f"{ep}: from={src!r} is not a box label on this page")
    if dst not in labels:
        raise SceneSpecError(f"{ep}: to={dst!r} is not a box label on this page")
    if labels[src] > 1:
        raise SceneSpecError(f"{ep}: from={src!r} is ambiguous (duplicate labels on this page)")
    if labels[dst] > 1:
        raise SceneSpecError(f"{ep}: to={dst!r} is ambiguous (duplicate labels on this page)")
    if src == dst:
        raise SceneSpecError(f"{ep}: from and to must differ")


def _validate_edge_decor(edge: dict[str, Any], ep: str) -> None:
    col = edge.get("color")
    if col is not None and str(col) not in ALLOWED_COLORS:
        raise SceneSpecError(f"{ep}: color must be one of {sorted(ALLOWED_COLORS)} if set")
    style = edge.get("style")
    if style is not None and str(style).strip().lower() not in ALLOWED_EDGE_STYLES:
        raise SceneSpecError(
            f"{ep}: style must be one of {sorted(ALLOWED_EDGE_STYLES)} if set"
        )
    label = edge.get("label")
    if label is None:
        return
    if not isinstance(label, str):
        raise SceneSpecError(f"{ep}: label must be a string if set")
    if len(label.strip()) > 40:
        raise SceneSpecError(f"{ep}: label must be at most 40 characters")


def _validate_edges(
    edges: Any,
    *,
    labels: dict[str, int],
    path_label: str,
) -> None:
    if edges is None:
        return
    if not isinstance(edges, list):
        raise SceneSpecError(f"{path_label}: edges must be a list if set")
    for i, edge in enumerate(edges):
        ep = f"{path_label}: edges[{i}]"
        if not isinstance(edge, dict):
            raise SceneSpecError(f"{ep}: edge must be a mapping")
        _validate_edge_ends(edge, ep, labels)
        _validate_edge_decor(edge, ep)


def _require_nonempty_str(value: Any, path_label: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SceneSpecError(f"{path_label}: {key} must be a non-empty string")


def _validate_required_keys(data: dict[str, Any], path_label: str) -> None:
    for key in SPEC_REQUIRED_TOP:
        if key not in data:
            raise SceneSpecError(f"{path_label}: missing required key {key!r}")
    _require_nonempty_str(data["segment_id"], path_label, "segment_id")
    _require_nonempty_str(data["class_name"], path_label, "class_name")
    timing_key = data.get("timing_key")
    if timing_key is not None and (not isinstance(timing_key, str) or not timing_key.strip()):
        raise SceneSpecError(f"{path_label}: timing_key must be a non-empty string if set")


def _validate_title_subtitle(title: dict[str, Any], path_label: str) -> None:
    subtitle = title.get("subtitle")
    if subtitle is None:
        return
    if not isinstance(subtitle, str):
        raise SceneSpecError(f"{path_label}: title.subtitle must be a string if set")
    if len(subtitle.strip()) > 80:
        raise SceneSpecError(f"{path_label}: title.subtitle must be at most 80 characters")


def _validate_title_block(title: Any, path_label: str) -> None:
    if not isinstance(title, dict):
        raise SceneSpecError(f"{path_label}: title must be a mapping")
    for fld in ("text", "font_size", "color"):
        if fld not in title:
            raise SceneSpecError(f"{path_label}: title.{fld} is required")
    if str(title["color"]) not in ALLOWED_COLORS:
        raise SceneSpecError(
            f"{path_label}: title.color must be one of {sorted(ALLOWED_COLORS)}"
        )
    font_size = title["font_size"]
    if not _is_yaml_number(font_size) or font_size <= 0:
        raise SceneSpecError(f"{path_label}: title.font_size must be a positive number")
    _validate_title_subtitle(title, path_label)


def _validate_page_transition_fields(layout: dict[str, Any], path_label: str) -> Any:
    transition = layout.get("page_transition", "fade")
    if str(transition) not in ALLOWED_PAGE_TRANSITIONS:
        raise SceneSpecError(
            f"{path_label}: layout.page_transition must be one of {sorted(ALLOWED_PAGE_TRANSITIONS)}"
        )
    run_time = layout.get("page_transition_run_time", 0.45)
    if not _is_yaml_number(run_time) or not (0 < float(run_time) <= 5.0):
        raise SceneSpecError(
            f"{path_label}: layout.page_transition_run_time must be a number in (0, 5] if set"
        )
    return transition


def _validate_dwell_fields(layout: dict[str, Any], path_label: str) -> None:
    dwell_mode = layout.get("dwell_emphasis", "auto")
    if str(dwell_mode).strip().lower() not in ALLOWED_DWELL_EMPHASIS:
        raise SceneSpecError(
            f"{path_label}: layout.dwell_emphasis must be one of "
            f"{sorted(ALLOWED_DWELL_EMPHASIS)} if set"
        )
    if "dwell_run_time" not in layout:
        return
    dwell_rt = layout.get("dwell_run_time")
    if not _is_yaml_number(dwell_rt) or not (0 < float(dwell_rt) <= 3.0):
        raise SceneSpecError(
            f"{path_label}: layout.dwell_run_time must be a number in (0, 3] if set"
        )


def _validate_layout_gaps(layout: dict[str, Any], path_label: str) -> None:
    for gap_key in ("first_row_title_buff", "row_gap", "column_gap"):
        if gap_key not in layout or layout.get(gap_key) is None:
            continue
        gap_val = layout[gap_key]
        if not _is_yaml_number(gap_val):
            raise SceneSpecError(
                f"{path_label}: layout.{gap_key} must be a YAML number, not "
                f"{type(gap_val).__name__} ({gap_val!r})"
            )


def _validate_layout_block(data: dict[str, Any], path_label: str) -> Any:
    layout = data.get("layout") or {}
    if layout and not isinstance(layout, dict):
        raise SceneSpecError(f"{path_label}: layout must be a mapping if present")
    transition = _validate_page_transition_fields(layout, path_label)
    _validate_dwell_fields(layout, path_label)
    _validate_layout_gaps(layout, path_label)
    return transition


def _validate_single_page_rows(data: dict[str, Any], path_label: str) -> None:
    rows = data["rows"]
    if not isinstance(rows, list) or not rows:
        raise SceneSpecError(f"{path_label}: rows must be a non-empty list")
    _validate_row_list(rows, path_label=path_label, prefix="rows")
    _validate_edges(data.get("edges"), labels=_page_box_labels(rows), path_label=path_label)


def _validate_page_entry(
    page: Any, pi: int, path_label: str, transition: Any
) -> None:
    pp = f"{path_label}: pages[{pi}]"
    if not isinstance(page, dict):
        raise SceneSpecError(f"{pp}: page must be a mapping")
    if "rows" not in page:
        raise SceneSpecError(f"{pp}: missing rows")
    rows = page["rows"]
    if not isinstance(rows, list) or not rows:
        raise SceneSpecError(f"{pp}: rows must be a non-empty list")
    _validate_row_list(rows, path_label=path_label, prefix=f"pages[{pi}].rows")
    _validate_edges(page.get("edges"), labels=_page_box_labels(rows), path_label=pp)
    if pi <= 0:
        return
    page_transition = page.get("transition", transition)
    if str(page_transition) not in ALLOWED_PAGE_TRANSITIONS:
        raise SceneSpecError(
            f"{pp}: transition must be one of {sorted(ALLOWED_PAGE_TRANSITIONS)} if set"
        )


def _validate_pages_block(data: dict[str, Any], path_label: str, transition: Any) -> None:
    if data.get("edges") is not None:
        raise SceneSpecError(
            f"{path_label}: top-level edges are only valid with rows; "
            f"put edges on each page for multi-page specs"
        )
    pages = data["pages"]
    if not isinstance(pages, list) or not pages:
        raise SceneSpecError(f"{path_label}: pages must be a non-empty list")
    for pi, page in enumerate(pages):
        _validate_page_entry(page, pi, path_label, transition)


def validate_scene_spec(data: dict[str, Any], *, path_label: str = "spec") -> None:
    _validate_required_keys(data, path_label)
    _validate_title_block(data["title"], path_label)
    has_pages = data.get("pages") is not None
    has_rows = data.get("rows") is not None
    if has_pages == has_rows:
        raise SceneSpecError(
            f"{path_label}: set exactly one of 'rows' (single page) or 'pages' (multi-page)"
        )
    transition = _validate_layout_block(data, path_label)
    if has_rows:
        _validate_single_page_rows(data, path_label)
        return
    _validate_pages_block(data, path_label, transition)


def _normalized_pages(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return page dicts with keys rows, transition, edges (None for first page transition)."""
    layout = spec.get("layout") or {}
    default_tr = str(layout.get("page_transition", "fade"))
    if spec.get("pages") is not None:
        pages_raw = spec["pages"]
        assert isinstance(pages_raw, list)
        out: list[dict[str, Any]] = []
        for pi, page in enumerate(pages_raw):
            tr = None if pi == 0 else str(page.get("transition", default_tr))
            edges = page.get("edges") if isinstance(page.get("edges"), list) else []
            out.append({"rows": page["rows"], "transition": tr, "edges": edges})
        return out
    edges = spec.get("edges") if isinstance(spec.get("edges"), list) else []
    return [{"rows": spec["rows"], "transition": None, "edges": edges}]


def _box_var_by_label(page_index: int, rows: list[Any]) -> dict[str, str]:
    """Map unique box label → generated Python variable name for that page."""
    out: dict[str, str] = {}
    for r, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        boxes = row.get("boxes") or []
        if not isinstance(boxes, list):
            continue
        for b, box in enumerate(boxes):
            if not isinstance(box, dict) or _is_image_element(box):
                continue
            lab = str(box.get("label", "")).strip()
            if lab:
                out[lab] = f"_bx_{page_index}_{r}_{b}"
    return out


def _any_wait_segment_in_pages(pages: list[dict[str, Any]]) -> bool:
    for page in pages:
        for row in page["rows"]:
            if row.get("wait_segment") is not None:
                return True
    return False


def _box_ctor_line(var: str, box: dict[str, Any]) -> str:
    """Emit ``_box(...)``; omit default ``shape='rounded'`` so stale helpers still work."""
    lab = str(box["label"])
    col = str(box["color"])
    w = float(box["width"])
    h = float(box["height"])
    fs = int(box["font_size"])
    extras: list[str] = []
    bsub = str(box.get("subtitle") or "").strip()
    if bsub:
        extras.append(f"subtitle={bsub!r}")
    shape = str(box.get("shape") or "rounded").strip().lower()
    if shape != "rounded":
        extras.append(f"shape={shape!r}")
    extra = (", " + ", ".join(extras)) if extras else ""
    return f"        {var} = _box({lab!r}, {col}, {w}, {h}, {fs}{extra})"


def _page_exit_call(target: str, transition: str) -> str:
    """Animation that takes one revealed mobject off before the next page."""
    kind = str(transition or "fade").strip().lower()
    if kind == "slide":
        return f"FadeOut({target}, shift=LEFT * {PAGE_SLIDE_SHIFT})"
    if kind == "rise":
        return f"FadeOut({target}, shift=DOWN * {PAGE_RISE_SHIFT})"
    if kind == "zoom":
        return f"FadeOut({target}, scale={PAGE_ZOOM_SCALE})"
    return f"FadeOut({target})"


def _page_enter_call(target: str, transition: str) -> str:
    """Entrance that continues the exit.

    Manim ``FadeIn(shift=v)`` starts at ``-v`` and moves by ``v`` into place.
    ``slide`` uses the same leftward vector as the exit, so the new node
    arrives from the right. ``rise`` only settles a short distance: a full
    exit drop would start the new node on top of the title.
    """
    kind = str(transition or "fade").strip().lower()
    if kind == "slide":
        return f"FadeIn({target}, shift=LEFT * {PAGE_SLIDE_SHIFT})"
    if kind == "rise":
        return f"FadeIn({target}, shift=DOWN * {PAGE_RISE_ENTER})"
    if kind == "zoom":
        return f"FadeIn({target}, scale={PAGE_ZOOM_SCALE})"
    return f"FadeIn({target})"


def _author_reveal(box: dict[str, Any]) -> str | None:
    raw = box.get("reveal")
    if raw is None:
        return None
    text = str(raw).strip().lower()
    return text or None


def _reveal_anim(bx: str, reveal: str) -> str:
    kind = str(reveal or "fade").strip().lower()
    if kind == "grow":
        return f"GrowFromCenter({bx})"
    if kind == "slide":
        return f"FadeIn({bx}, shift=UP * 0.22)"
    return f"FadeIn({bx})"


def _emphasis_anim(bx: str, emphasis: str) -> str | None:
    if emphasis == "ring":
        return f"Circumscribe({bx})"
    if emphasis == "pulse":
        return f"Indicate({bx})"
    return None


def _reject_nonfinite_compile_words(words: list[dict[str, Any]] | None) -> None:
    if not words:
        return
    from docgen.timestamps import TimestampError, require_finite_word_times

    try:
        require_finite_word_times(words, label="timing words")
    except TimestampError as exc:
        raise SceneSpecError(str(exc)) from exc


def _require_timing_key(spec: dict[str, Any]) -> str:
    timing_key = spec.get("timing_key")
    if not timing_key or not str(timing_key).strip():
        raise SceneSpecError(
            "timing_key is required (narration stem, e.g. 01-overview) — "
            "set in YAML or pass after resolving segment_names in docgen.yaml"
        )
    return str(timing_key).strip()


def _compile_reveal_index(
    spec: dict[str, Any],
    words: list[dict[str, Any]] | None,
) -> dict[tuple[int, int, int], RevealEvent]:
    reveal_by_key: dict[tuple[int, int, int], RevealEvent] = {}
    if not words:
        return reveal_by_key
    for ev in simulate_reveal_timeline(spec, words, clamp_run_times=True):
        reveal_by_key[(ev.page, ev.row, ev.box)] = ev
    return reveal_by_key


def _compile_title_run_time(
    spec: dict[str, Any],
    words: list[dict[str, Any]] | None,
) -> float:
    if not words:
        return TITLE_WRITE_RUN_TIME
    first_start = next(
        (
            float(s["word_start"])
            for s in iter_reveal_slots(spec, words)
            if s["word_start"] is not None
        ),
        None,
    )
    return clamp_title_run_time(TITLE_WRITE_RUN_TIME, first_start)


def _compile_title_lines(
    title: dict[str, Any],
    title_rt: float,
) -> list[str]:
    title_text = str(title["text"])
    title_fs = int(title["font_size"])
    title_color = str(title["color"])
    title_subtitle = str(title.get("subtitle") or "").strip()
    if not title_subtitle:
        return [
            f"        title = Text({title_text!r}, font_size={title_fs}, color={title_color}, font=MANIM_FONT).to_edge(UP)",
            f"        self.timed_play(Write(title), run_time={title_rt})",
            "",
        ]
    sub_fs = max(14, title_fs - 10)
    return [
        f"        _title_main = Text({title_text!r}, font_size={title_fs}, color={title_color}, font=MANIM_FONT)",
        f"        _title_sub = Text({title_subtitle!r}, font_size={sub_fs}, color={title_color}, font=MANIM_FONT)",
        "        _title_sub.set_opacity(0.85)",
        "        title = VGroup(_title_main, _title_sub).arrange(DOWN, buff=0.12).to_edge(UP)",
        f"        self.timed_play(Write(title), run_time={title_rt})",
        "",
    ]


def _page_contains_image(rows: list[Any]) -> bool:
    for row in rows:
        for box in row.get("boxes") or []:
            if _is_image_element(box):
                return True
    return False


def _append_page_boxes(lines: list[str], page_index: int, rows: list[Any]) -> None:
    for r, row in enumerate(rows):
        boxes_raw = row["boxes"]
        for b, box in enumerate(boxes_raw):
            var = f"_bx_{page_index}_{r}_{b}"
            w = float(box["width"])
            h = float(box["height"])
            if _is_image_element(box):
                rel = str(box["image"]).strip()
                lines.append(f"        {var} = _image({rel!r}, {w}, {h})")
            else:
                lines.append(_box_ctor_line(var, box))


def _append_page_rows(
    lines: list[str],
    page_index: int,
    rows: list[Any],
    *,
    page_has_image: bool,
    column_gap: float,
) -> None:
    container = "Group" if page_has_image else "VGroup"
    for r, row in enumerate(rows):
        boxes_raw = row["boxes"]
        box_names = [f"_bx_{page_index}_{r}_{b}" for b in range(len(boxes_raw))]
        row_var = f"_row_{page_index}_{r}"
        if len(box_names) == 1:
            lines.append(f"        {row_var} = {container}({box_names[0]})")
        else:
            joined = ", ".join(box_names)
            lines.append(
                f"        {row_var} = {container}({joined}).arrange(RIGHT, buff={column_gap})"
            )


def _append_page_stack(
    lines: list[str],
    page_index: int,
    row_count: int,
    *,
    page_has_image: bool,
    row_gap: float,
    first_row_title_buff: float,
) -> None:
    row_refs = ", ".join(f"_row_{page_index}_{r}" for r in range(row_count))
    stack_var = f"_p{page_index}_stack"
    container = "Group" if page_has_image else "VGroup"
    lines.append(
        f"        {stack_var} = {container}({row_refs}).arrange(DOWN, buff={row_gap}, center=True)"
    )
    lines.append(f"        {stack_var}.next_to(title, DOWN, buff={first_row_title_buff})")


def _edge_anim_kind(style: str, label: str) -> str:
    if style == "solid" and not label:
        return "grow"
    return "fade"


def _append_page_edges(
    lines: list[str],
    page_index: int,
    rows: list[Any],
    edges: list[Any],
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> None:
    label_vars = _box_var_by_label(page_index, rows)
    for ei, edge in enumerate(edges):
        if isinstance(edge, dict):
            _append_one_edge(
                lines,
                page_index,
                ei,
                edge,
                label_vars,
                edges_with_target,
                page_edge_vars,
            )


def _append_one_edge(
    lines: list[str],
    page_index: int,
    edge_index: int,
    edge: dict[str, Any],
    label_vars: dict[str, str],
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> None:
    src = str(edge["from"]).strip()
    dst = str(edge["to"]).strip()
    src_var = label_vars.get(src)
    dst_var = label_vars.get(dst)
    if not src_var or not dst_var:
        return
    evar = f"_ar_{page_index}_{edge_index}"
    ecol = str(edge.get("color") or "C_ACCENT")
    estyle = str(edge.get("style") or "solid").strip().lower() or "solid"
    elabel = str(edge.get("label") or "").strip()
    lines.append(f"        {evar} = _arrow({src_var}, {dst_var}, {ecol}, style={estyle!r})")
    page_edge_vars.setdefault(page_index, []).append(evar)
    order = {v: i for i, v in enumerate(label_vars.values())}
    later = dst_var if order.get(dst_var, 0) >= order.get(src_var, 0) else src_var
    anim = _edge_anim_kind(estyle, elabel)
    edges_with_target.setdefault((page_index, later), []).append((evar, anim))
    if not elabel:
        return
    lvar = f"{evar}_lbl"
    lines.append(f"        {lvar} = Text({elabel!r}, font_size=16, color={ecol}, font=MANIM_FONT)")
    lines.append(f"        {lvar}.move_to({evar}.get_center()).shift(UP * 0.22)")
    page_edge_vars.setdefault(page_index, []).append(lvar)
    edges_with_target.setdefault((page_index, later), []).append((lvar, "fade"))


def _append_page_geometry(
    lines: list[str],
    page_index: int,
    page: dict[str, Any],
    *,
    column_gap: float,
    row_gap: float,
    first_row_title_buff: float,
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> None:
    rows = page["rows"]
    page_has_image = _page_contains_image(rows)
    _append_page_boxes(lines, page_index, rows)
    _append_page_rows(
        lines,
        page_index,
        rows,
        page_has_image=page_has_image,
        column_gap=column_gap,
    )
    _append_page_stack(
        lines,
        page_index,
        len(rows),
        page_has_image=page_has_image,
        row_gap=row_gap,
        first_row_title_buff=first_row_title_buff,
    )
    _append_page_edges(
        lines,
        page_index,
        rows,
        list(page.get("edges") or []),
        edges_with_target,
        page_edge_vars,
    )


def _reject_wait_segments(pages: list[dict[str, Any]]) -> None:
    if not _any_wait_segment_in_pages(pages):
        return
    raise SceneSpecError(
        "wait_segment is not supported in compiled scenes — use wait_word (timing.json "
        "`words` index) only. Run `docgen scene-compile` so rows are upgraded from Whisper "
        "words, or edit the YAML to use wait_word."
    )


def _page_box_vars(pages: list[dict[str, Any]]) -> dict[int, list[str]]:
    """Revealed box names. Page exits fade these, not the parent group."""
    out: dict[int, list[str]] = {}
    for p, page in enumerate(pages):
        for r, row in enumerate(page["rows"]):
            boxes_raw = row.get("boxes") or []
            if isinstance(boxes_raw, list):
                _collect_page_boxes(out, p, r, boxes_raw)
    return out


def _collect_page_boxes(
    out: dict[int, list[str]],
    page_index: int,
    row_index: int,
    boxes_raw: list[Any],
) -> None:
    for b_idx, box in enumerate(boxes_raw):
        if isinstance(box, dict):
            out.setdefault(page_index, []).append(f"_bx_{page_index}_{row_index}_{b_idx}")


def _resolved_wait_word(box: dict[str, Any], box_index: int, row_wait: Any) -> Any:
    ww = box.get("wait_word")
    if ww is None and box_index == 0 and row_wait is not None:
        return row_wait
    return ww


def _scheduled_run_time(ev: RevealEvent | None, row_run_time: float) -> float:
    if ev is None:
        return row_run_time
    return round(float(ev.run_time), 3)


def _scheduled_page_fade(ev: RevealEvent | None, default_rt: float) -> float:
    if ev is None:
        return default_rt
    return round(float(ev.page_fade_out), 3)


def _append_page_exit(
    lines: list[str],
    transition: str,
    fade_targets: list[str],
    page_fade_rt: float,
) -> str | None:
    if transition == "none":
        for target in fade_targets:
            lines.append(f"        self.remove({target})")
        lines.append("        self.timed_wait(0.05)")
        return None
    kind = transition if transition in ANIMATED_PAGE_TRANSITIONS else "fade"
    if fade_targets:
        fade_args = ", ".join(_page_exit_call(target, kind) for target in fade_targets)
        lines.append(f"        self.timed_play({fade_args}, run_time={page_fade_rt})")
    else:
        lines.append(f"        self.timed_wait({page_fade_rt})")
    return kind


def _opening_page_transition(page: dict[str, Any]) -> str:
    return str(page.get("transition") or "fade")


def _append_incoming_exit(
    lines: list[str],
    *,
    page_index: int,
    row_index: int,
    box_index: int,
    page: dict[str, Any],
    page_box_vars: dict[int, list[str]],
    page_edge_vars: dict[int, list[str]],
    page_fade_rt: float,
) -> str | None:
    if page_index <= 0 or row_index != 0 or box_index != 0:
        return None
    targets = list(page_box_vars.get(page_index - 1) or [])
    targets.extend(page_edge_vars.get(page_index - 1) or [])
    return _append_page_exit(
        lines,
        _opening_page_transition(page),
        targets,
        page_fade_rt,
    )


def _reveal_statement(
    bx: str,
    box: dict[str, Any],
    ev: RevealEvent | None,
    *,
    page_has_edges: bool,
    first_box_seen: bool,
    page_enter_trans: str | None,
) -> str:
    author_reveal = _author_reveal(box)
    use_page_enter = page_enter_trans in {"slide", "rise", "zoom"} and author_reveal is None
    if use_page_enter:
        return _page_enter_call(bx, str(page_enter_trans))
    if ev is not None:
        reveal = str(ev.reveal)
    else:
        reveal = default_box_reveal(
            box,
            page_has_edges=page_has_edges,
            is_first_on_page=not first_box_seen,
        )
    return _reveal_anim(bx, reveal)


def _edge_play_part(evar: str, kind: str) -> str:
    if kind == "grow":
        return f"GrowArrow({evar})"
    return f"FadeIn({evar})"


def _append_reveal_play(
    lines: list[str],
    bx: str,
    reveal_part: str,
    edge_anims: list[tuple[str, str]],
    run_time: float,
) -> None:
    parts = [reveal_part]
    for evar, kind in edge_anims:
        parts.append(_edge_play_part(evar, kind))
    anims = ", ".join(parts)
    lines.append(f"        self.timed_play({anims}, run_time={run_time})")


def _hold_pulses_for(ev: RevealEvent | None) -> tuple[HoldPulse, ...]:
    if ev is None:
        return ()
    if ev.hold_pulses:
        return ev.hold_pulses
    if float(ev.dwell_run_time) < MIN_DWELL_RUN_TIME:
        return ()
    return (
        HoldPulse(
            wait_before=0.0,
            run_time=float(ev.dwell_run_time),
            emphasis=str(ev.emphasis),
        ),
    )


def _append_hold_pulses(lines: list[str], bx: str, ev: RevealEvent | None) -> None:
    for pulse in _hold_pulses_for(ev):
        _append_one_pulse(lines, bx, pulse)


def _append_one_pulse(lines: list[str], bx: str, pulse: HoldPulse) -> None:
    if float(pulse.wait_before) > 0:
        lines.append(f"        self.timed_wait({round(float(pulse.wait_before), 3)})")
    emph = _emphasis_anim(bx, str(pulse.emphasis))
    if emph and float(pulse.run_time) >= MIN_DWELL_RUN_TIME:
        lines.append(
            f"        self.timed_play({emph}, run_time={round(float(pulse.run_time), 3)})"
        )


def _append_one_box_playback(
    lines: list[str],
    *,
    page_index: int,
    row_index: int,
    box_index: int,
    box: dict[str, Any],
    row_run_time: float,
    row_wait: Any,
    page: dict[str, Any],
    page_has_edges: bool,
    first_box_seen: bool,
    ev: RevealEvent | None,
    page_tr_run: float,
    page_box_vars: dict[int, list[str]],
    page_edge_vars: dict[int, list[str]],
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
) -> None:
    run_time = _scheduled_run_time(ev, row_run_time)
    page_fade_rt = _scheduled_page_fade(ev, page_tr_run)
    ww = _resolved_wait_word(box, box_index, row_wait)
    if ww is not None:
        lines.append(f"        self.wait_until_word(timing_words, {int(ww)})")
    page_enter_trans = _append_incoming_exit(
        lines,
        page_index=page_index,
        row_index=row_index,
        box_index=box_index,
        page=page,
        page_box_vars=page_box_vars,
        page_edge_vars=page_edge_vars,
        page_fade_rt=page_fade_rt,
    )
    bx = f"_bx_{page_index}_{row_index}_{box_index}"
    reveal_part = _reveal_statement(
        bx,
        box,
        ev,
        page_has_edges=page_has_edges,
        first_box_seen=first_box_seen,
        page_enter_trans=page_enter_trans,
    )
    _append_reveal_play(
        lines,
        bx,
        reveal_part,
        edges_with_target.get((page_index, bx), []),
        run_time,
    )
    _append_hold_pulses(lines, bx, ev)


def _append_page_playback(
    lines: list[str],
    page_index: int,
    page: dict[str, Any],
    *,
    reveal_by_key: dict[tuple[int, int, int], RevealEvent],
    page_tr_run: float,
    page_box_vars: dict[int, list[str]],
    page_edge_vars: dict[int, list[str]],
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
) -> None:
    page_has_edges = bool(page.get("edges"))
    first_box_seen = False
    for row_index, row in enumerate(page["rows"]):
        first_box_seen = _append_row_playback(
            lines,
            page_index=page_index,
            row_index=row_index,
            row=row,
            page=page,
            page_has_edges=page_has_edges,
            first_box_seen=first_box_seen,
            reveal_by_key=reveal_by_key,
            page_tr_run=page_tr_run,
            page_box_vars=page_box_vars,
            page_edge_vars=page_edge_vars,
            edges_with_target=edges_with_target,
        )


def _append_row_playback(
    lines: list[str],
    *,
    page_index: int,
    row_index: int,
    row: dict[str, Any],
    page: dict[str, Any],
    page_has_edges: bool,
    first_box_seen: bool,
    reveal_by_key: dict[tuple[int, int, int], RevealEvent],
    page_tr_run: float,
    page_box_vars: dict[int, list[str]],
    page_edge_vars: dict[int, list[str]],
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
) -> bool:
    boxes_raw = row["boxes"]
    if not isinstance(boxes_raw, list):
        return first_box_seen
    row_run_time = float(row["run_time"])
    row_wait = row.get("wait_word")
    for box_index, box in enumerate(boxes_raw):
        if isinstance(box, dict):
            _append_one_box_playback(
                lines,
                page_index=page_index,
                row_index=row_index,
                box_index=box_index,
                box=box,
                row_run_time=row_run_time,
                row_wait=row_wait,
                page=page,
                page_has_edges=page_has_edges,
                first_box_seen=first_box_seen,
                ev=reveal_by_key.get((page_index, row_index, box_index)),
                page_tr_run=page_tr_run,
                page_box_vars=page_box_vars,
                page_edge_vars=page_edge_vars,
                edges_with_target=edges_with_target,
            )
            first_box_seen = True
    return first_box_seen


def _append_audio_tail(lines: list[str], timing_key: str) -> None:
    lines.extend(
        [
            "",
            "        # docgen: audio-length tail (waits through full TTS; run after `docgen timestamps`)",
            "        if timing_words:",
            "            self.wait_until(",
            '                max(float(w.get("end", 0.0)) for w in timing_words)',
            "            )",
            "        else:",
            f"            _docgen_segs = _load_timing({timing_key!r})",
            "            if _docgen_segs:",
            "                self.wait_until(",
            '                    max(float(s.get("end", 0.0)) for s in _docgen_segs)',
            "                )",
            "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)",
            "        self.timed_wait(0.5)",
        ]
    )


def compile_scene_class(
    spec: dict[str, Any],
    *,
    words: list[dict[str, Any]] | None = None,
) -> str:
    """Return a full ``class Name(_TimedScene): ...`` definition (no imports).

    ``spec`` must include ``timing_key`` (narration audio stem for ``timing.json``),
    either in the mapping or merged by the caller from ``Config.resolve_segment_name``.

    When ``words`` is provided (normal ``scene-compile`` / retime path), FadeIn and
    page-transition durations are **clamped** so ``_TimedScene._clock`` cannot race
    past the next ``wait_word`` start — otherwise the first board dumps and freezes
    while narration continues (issue #66).
    """
    validate_scene_spec(spec, path_label="spec")
    _reject_nonfinite_compile_words(words)
    class_name = str(spec["class_name"]).strip()
    timing_key = _require_timing_key(spec)
    layout = spec.get("layout") or {}
    first_row_title_buff = float(layout.get("first_row_title_buff", 0.5))
    row_gap = float(layout.get("row_gap", 0.6))
    column_gap = float(layout.get("column_gap", 0.8))
    page_tr_run = float(layout.get("page_transition_run_time", 0.45))
    pages = _normalized_pages(spec)
    _reject_wait_segments(pages)
    reveal_by_key = _compile_reveal_index(spec, words)
    title_rt = _compile_title_run_time(spec, words)
    lines: list[str] = [
        f"class {class_name}(_TimedScene):",
        "    def construct(self):",
        "        self.camera.background_color = C_BG",
        f"        timing_words = _load_timing_words({timing_key!r})",
        "",
    ]
    lines.extend(_compile_title_lines(spec["title"], title_rt))
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]] = {}
    page_edge_vars: dict[int, list[str]] = {}
    for page_index, page in enumerate(pages):
        _append_page_geometry(
            lines,
            page_index,
            page,
            column_gap=column_gap,
            row_gap=row_gap,
            first_row_title_buff=first_row_title_buff,
            edges_with_target=edges_with_target,
            page_edge_vars=page_edge_vars,
        )
    lines.append("")
    revealed = _page_box_vars(pages)
    for page_index, page in enumerate(pages):
        _append_page_playback(
            lines,
            page_index,
            page,
            reveal_by_key=reveal_by_key,
            page_tr_run=page_tr_run,
            page_box_vars=revealed,
            page_edge_vars=page_edge_vars,
            edges_with_target=edges_with_target,
        )
    _append_audio_tail(lines, timing_key)
    return "\n".join(lines) + "\n"
