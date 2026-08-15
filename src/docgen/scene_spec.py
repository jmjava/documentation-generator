"""Declarative Manim scene specs (YAML) compiled to compliant Python.

LLMs are poor at reliable 2D layout in raw Manim code.  Instead they (or
humans) author a small **scene spec** — rows of labeled boxes, colors, and
optional ``wait_word`` indices on each **box** into the Whisper **words** list in ``timing.json``
(wait until that token's ``start``). Rows may still carry legacy ``wait_segment`` or a single
``wait_word`` (applied only to the **first** box in that row after compile). On-disk YAML may
still list legacy ``wait_segment``; ``docgen scene-compile`` upgrades those to the first box's
``wait_word`` when ``words`` exist.
``class ...(_TimedScene)`` body that:

* Lays out each **page** as a vertical stack of rows (``VGroup`` per row,
  then ``arrange(DOWN)``), positioned under the title — **no scaling** to cram
  content; use multiple **pages** when the story needs more boxes than fit.
* Between pages, runs a **page transition** (default ``fade`` out the previous
  page's stack) so the next page appears on a clear canvas.
* Uses the shared ``_box`` helper (text centered in the node; optional
  ``shape`` / ``reveal`` / ``emphasis``). After each paced reveal, a **dwell**
  slot may play ``Indicate`` / ``Circumscribe`` when the gap to the next
  ``wait_word`` is long enough — clamped so ``_clock`` cannot race.

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
    MIN_DWELL_RUN_TIME,
    compute_dwell_run_time,
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

ALLOWED_PAGE_TRANSITIONS = frozenset({"fade", "none"})
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
    if not isinstance(fs, (int, float)):
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

    def _row_width(boxes: list[dict[str, Any]]) -> float:
        ws = [float(b.get("width", 0)) for b in boxes]
        if not ws:
            return 0.0
        return sum(ws) + max(0, len(ws) - 1) * col_gap

    def _fit_boxes(boxes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        if not boxes:
            return []
        rw = _row_width(boxes)
        if rw <= safe + 0.05:
            return [boxes]
        # Proportional scale down to safe width.
        scale = safe / rw if rw > 0 else 1.0
        scaled = []
        for b in boxes:
            nb = dict(b)
            try:
                nb["width"] = max(min_box_w, float(b["width"]) * scale)
            except (KeyError, TypeError, ValueError):
                pass
            scaled.append(nb)
        if _row_width(scaled) <= safe + 0.05:
            return [scaled]
        # Still too wide: split into chunks of ≤3, then scale each chunk.
        chunks: list[list[dict[str, Any]]] = []
        for i in range(0, len(boxes), 3):
            part = [dict(b) for b in boxes[i : i + 3]]
            prw = _row_width(part)
            if prw > safe + 0.05 and prw > 0:
                pscale = safe / prw
                for b in part:
                    try:
                        b["width"] = max(min_box_w, float(b["width"]) * pscale)
                    except (KeyError, TypeError, ValueError):
                        pass
            chunks.append(part)
        return chunks

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

    # Source rows + per-source-page transition (preserve existing carving + transitions).
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
    else:
        rows = spec.get("rows")
        if not isinstance(rows, list) or not rows:
            return spec
        src_pages = [(list(rows), None)]

    def _split_rows_to_pages(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
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

    new_pages: list[dict[str, Any]] = []
    for page_idx, (rows, tr) in enumerate(src_pages):
        chunks = _split_rows_to_pages(rows)
        for chunk_idx, chunk in enumerate(chunks):
            entry: dict[str, Any] = {"rows": chunk}
            # First chunk of first source page has no transition; later chunks fade in
            # over the previous page; preserve the source page's transition for its first chunk.
            if not (page_idx == 0 and chunk_idx == 0):
                if chunk_idx == 0 and tr is not None:
                    entry["transition"] = tr
                else:
                    entry["transition"] = transition_default
            new_pages.append(entry)

    # If nothing changed (single page, no split), keep the original ``rows`` form.
    only_one = len(new_pages) == 1 and "transition" not in new_pages[0]
    if only_one and spec.get("rows") is not None and spec.get("pages") is None:
        return spec

    new_spec = dict(spec)
    new_spec.pop("rows", None)
    new_spec["pages"] = new_pages
    return new_spec


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
        # Glue 2+ label tokens into one Whisper word (hyphenated / dotted compounds).
        glued = tokens[ti]
        matched_k: int | None = None
        for k in range(2, m - ti + 1):
            glued += tokens[ti + k - 1]
            if glued == spoken:
                matched_k = k
                break
            # Spoken word is longer only when TTS/Whisper glued extra chars we already
            # normalized away (rare); require exact equality for compounds.
            if len(glued) > len(spoken):
                break
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

    word_stream: list[tuple[str, float, int]] = []
    for wi, w in enumerate(words):
        if not isinstance(w, dict):
            continue
        nw = _normalize_word(w.get("word", ""))
        if not nw:
            continue
        try:
            start = float(w.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        word_stream.append((nw, start, wi))

    if not word_stream:
        return spec

    cursor = 0

    def _find_label(label: str, from_idx: int) -> tuple[int, int] | None:
        """Return (last matched stream index, original ``words`` index of phrase start)."""
        tokens = _label_tokens(label)
        if not tokens:
            return None
        norms = [w[0] for w in word_stream]
        n = len(word_stream)
        i = from_idx
        while i < n:
            last = _consume_label_tokens_at(tokens, norms, i)
            if last is not None:
                return (last, word_stream[i][2])
            i += 1
        return None

    def _process_rows(rows: list[Any]) -> None:
        nonlocal cursor
        for row in rows:
            if not isinstance(row, dict):
                continue
            row.pop("wait_at", None)
            boxes = row.get("boxes")
            if not isinstance(boxes, list) or not boxes:
                continue

            if not overwrite and (
                row.get("wait_word") is not None or row.get("wait_segment") is not None
            ):
                first = boxes[0]
                if isinstance(first, dict):
                    found = _find_label(str(first.get("label", "")), cursor)
                    if found is not None:
                        cursor = found[0] + 1
                continue

            if overwrite:
                row.pop("wait_word", None)
                row.pop("wait_segment", None)

            for box in boxes:
                if not isinstance(box, dict):
                    continue
                box.pop("wait_at", None)
                if box.get("image") is not None and not str(box.get("label", "")).strip():
                    # Unlabeled image element: no transcript anchor to re-derive from,
                    # so keep any author-provided wait_word as-is.
                    continue
                if not overwrite and box.get("wait_word") is not None:
                    found = _find_label(str(box.get("label", "")), cursor)
                    if found is not None:
                        cursor = found[0] + 1
                    continue

                label = str(box.get("label", ""))
                found = _find_label(label, cursor)
                if found is not None:
                    last_stream_i, first_word_i = found
                    box["wait_word"] = int(first_word_i)
                    box.pop("wait_segment", None)
                    cursor = last_stream_i + 1
                elif overwrite:
                    # Fail-closed: never keep a leftover LLM / legacy index for an
                    # unmatched spoken label — callers must reject or set pace: none.
                    box.pop("wait_word", None)
                    box.pop("wait_segment", None)

    new_spec = dict(spec)
    if new_spec.get("pages") is not None:
        new_pages = []
        for page in new_spec["pages"]:
            page = dict(page) if isinstance(page, dict) else page
            if isinstance(page, dict) and isinstance(page.get("rows"), list):
                page["rows"] = [dict(r) if isinstance(r, dict) else r for r in page["rows"]]
                _process_rows(page["rows"])
            new_pages.append(page)
        new_spec["pages"] = new_pages
    elif isinstance(new_spec.get("rows"), list):
        new_spec["rows"] = [dict(r) if isinstance(r, dict) else r for r in new_spec["rows"]]
        _process_rows(new_spec["rows"])
    return new_spec


def _pace_none(obj: dict[str, Any]) -> bool:
    return str(obj.get("pace", "")).strip().lower() == "none"


def pacing_violations(spec: dict[str, Any], *, words_present: bool) -> list[str]:
    """Return issues when timing words exist but story boxes lack ``wait_word``.

    Unpaced cascading ``timed_play`` finishes the board early and freezes through
    the rest of the narration. Opt out per box/row with ``pace: none``.
    Unlabeled image elements are exempt (no spoken anchor).
    """
    if not words_present:
        return []
    issues: list[str] = []
    pages = _spec_pages_rows(spec)
    for pi, rows in enumerate(pages):
        for ri, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row_opt_out = _pace_none(row)
            boxes = row.get("boxes")
            if not isinstance(boxes, list):
                continue
            prefix = f"pages[{pi}].rows[{ri}]" if spec.get("pages") is not None else f"rows[{ri}]"
            for bi, box in enumerate(boxes):
                if not isinstance(box, dict):
                    continue
                if row_opt_out or _pace_none(box):
                    continue
                if _is_image_element(box) and not str(box.get("label", "")).strip():
                    continue
                label = str(box.get("label", "")).strip()
                if not label:
                    continue
                if box.get("wait_word") is None:
                    issues.append(
                        f"{prefix}.boxes[{bi}]: label {label!r} has no wait_word match in "
                        "timing.json words — use a spoken phrase from the narration, or set "
                        "pace: none to opt out of beat sync"
                    )
    return issues


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
                if not isinstance(box, dict) or _pace_none(box):
                    continue
                label = str(box.get("label", "")).strip()
                ww = box.get("wait_word")
                if not label or ww is None:
                    continue
                try:
                    wi = int(ww)
                except (TypeError, ValueError):
                    continue
                if wi < 0 or wi >= len(words):
                    continue
                w = words[wi]
                if not isinstance(w, dict):
                    continue
                try:
                    t = float(w.get("start", 0.0))
                except (TypeError, ValueError):
                    continue
                out.append((label, t))
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
        return float(w.get("start", 0.0))
    except (TypeError, ValueError):
        return None


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
    pages = _normalized_pages(working)
    layout = working.get("layout") or {}
    default_tr = str(layout.get("page_transition", "fade"))
    default_tr_rt = float(layout.get("page_transition_run_time", 0.45))
    slots: list[dict[str, Any]] = []
    for p, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        rows = page.get("rows")
        if not isinstance(rows, list):
            continue
        trans = page.get("transition", default_tr)
        for r, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            boxes = row.get("boxes")
            if not isinstance(boxes, list):
                continue
            try:
                row_rt = float(row.get("run_time", 1.0))
            except (TypeError, ValueError):
                row_rt = 1.0
            for b, box in enumerate(boxes):
                if not isinstance(box, dict):
                    continue
                if box.get("image") is not None and not str(box.get("label", "")).strip():
                    # Unlabeled image: still revealed, but no spoken wait.
                    label = ""
                else:
                    label = str(box.get("label", "")).strip()
                ww = _box_wait_word(row, box, b)
                slots.append(
                    {
                        "page": p,
                        "row": r,
                        "box": b,
                        "label": label,
                        "wait_word": ww,
                        "word_start": _word_start_at(words or [], ww),
                        "run_time": row_rt,
                        "page_transition": str(trans or default_tr),
                        "page_transition_run_time": default_tr_rt,
                        "emphasis": resolve_box_emphasis(box, layout),
                        "reveal": str(box.get("reveal") or "fade").strip().lower(),
                    }
                )
    return slots


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

    clock = float(title_run_time)
    events: list[RevealEvent] = []

    for i, slot in enumerate(slots):
        word_start = slot["word_start"]
        ww = slot["wait_word"]
        wait_skipped = False
        if ww is not None and word_start is not None:
            target = float(word_start)
            if target > clock + 0.05:
                clock = target
            elif clock > target + 0.05:
                # Truly late: prior FadeIn/title already passed this spoken start.
                wait_skipped = True
            else:
                # On-time within tolerance (clamp landed on the beat).
                clock = max(clock, target)

        page_fade_out = 0.0
        if (
            int(slot["page"]) > 0
            and int(slot["row"]) == 0
            and int(slot["box"]) == 0
            and str(slot["page_transition"]) == "fade"
        ):
            page_fade_out = float(slot["page_transition_run_time"])

        next_target: float | None = None
        for nxt in slots[i + 1 :]:
            if nxt["wait_word"] is not None and nxt["word_start"] is not None:
                next_target = float(nxt["word_start"])
                break

        rt = float(slot["run_time"])
        if clamp_run_times and next_target is not None:
            budget = next_target - clock
            if page_fade_out + rt > budget and budget > 0:
                # Prefer keeping a short FadeIn; shrink page fade first.
                if page_fade_out > 0 and page_fade_out > max(0.0, budget - MIN_REVEAL_RUN_TIME):
                    page_fade_out = max(0.05, budget - MIN_REVEAL_RUN_TIME)
                remain = next_target - (clock + page_fade_out)
                if remain < rt:
                    rt = max(MIN_REVEAL_RUN_TIME, remain)
            elif budget <= 0:
                page_fade_out = 0.05 if page_fade_out > 0 else 0.0
                rt = MIN_REVEAL_RUN_TIME

        if page_fade_out > 0:
            clock += page_fade_out

        clock_after_reveal = clock + rt
        requested = str(slot.get("emphasis") or "none")
        default_dwell = float(
            (spec.get("layout") or {}).get("dwell_run_time", DEFAULT_DWELL_RUN_TIME)
        )
        dwell_rt = compute_dwell_run_time(
            clock_after_reveal,
            next_target,
            requested=requested,
            default_rt=default_dwell,
        )
        emphasis = requested if dwell_rt > 0 else "none"

        events.append(
            RevealEvent(
                label=str(slot["label"]),
                page=int(slot["page"]),
                row=int(slot["row"]),
                box=int(slot["box"]),
                wait_word=ww,
                word_start=word_start,
                effective_at=float(clock),
                wait_skipped=wait_skipped,
                run_time=float(rt),
                page_fade_out=float(page_fade_out),
                emphasis=emphasis,
                dwell_run_time=float(dwell_rt),
                reveal=str(slot.get("reveal") or "fade"),
            )
        )
        clock = clock_after_reveal + dwell_rt

    return events


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
    paced = [e for e in events if e.wait_word is not None]
    if paced:
        skipped = sum(1 for e in paced if e.wait_skipped)
        skip_ratio = skipped / len(paced)
        if skip_ratio > max_skip_ratio and skipped >= 2:
            issues.append(
                f"wait_until_word no-op ratio {skip_ratio:.0%} ({skipped}/{len(paced)}) "
                f"exceeds max_skip_ratio={max_skip_ratio:.0%} — FadeIn/title run_time "
                "pushed _clock past spoken word starts (first board dumps, then freezes)"
            )
        streak = 0
        best = 0
        for e in paced:
            if e.wait_skipped:
                streak += 1
                best = max(best, streak)
            else:
                streak = 0
        if best > max_consecutive_skips:
            issues.append(
                f"{best} consecutive skipped waits (max_consecutive_skips="
                f"{max_consecutive_skips}) — boxes cascade with only FadeIn gaps"
            )

    last_effective = max(e.effective_at for e in events)
    early_idle = audio_end - last_effective
    early_ratio = early_idle / audio_end if audio_end > 0 else 0.0
    if early_idle > max_early_sec and early_ratio > max_early_ratio:
        issues.append(
            f"effective last reveal at {last_effective:.2f}s leaves "
            f"early_idle={early_idle:.2f}s ({early_ratio:.0%} of audio_end="
            f"{audio_end:.2f}s) — visual story finished on the Manim clock long "
            "before narration ends"
        )
    return issues


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
            if not isinstance(row, dict):
                continue
            ws = row.get("wait_segment")
            if ws is None:
                continue
            boxes = row.get("boxes")
            if not isinstance(boxes, list) or not boxes or not isinstance(boxes[0], dict):
                row.pop("wait_segment", None)
                continue
            if boxes[0].get("wait_word") is None:
                boxes[0]["wait_word"] = wait_word_index_at_segment_start(
                    segments, words, int(ws)
                )
            row.pop("wait_segment", None)

    out = dict(spec)
    if out.get("pages") is not None:
        new_pages: list[Any] = []
        for page in out["pages"]:
            p = dict(page) if isinstance(page, dict) else page
            if isinstance(p, dict) and isinstance(p.get("rows"), list):
                p["rows"] = [dict(r) if isinstance(r, dict) else r for r in p["rows"]]
                _rows(p["rows"])
            new_pages.append(p)
        out["pages"] = new_pages
    elif isinstance(out.get("rows"), list):
        out["rows"] = [dict(r) if isinstance(r, dict) else r for r in out["rows"]]
        _rows(out["rows"])
    return out


def spec_rows_reference_whisper_waits(spec: dict[str, Any]) -> bool:
    """True if any row or box references Whisper pacing (needs timing enrichment)."""
    for rows in _spec_pages_rows(spec):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("wait_word") is not None or row.get("wait_segment") is not None:
                return True
            for box in row.get("boxes") or []:
                if isinstance(box, dict) and (
                    box.get("wait_word") is not None or box.get("wait_segment") is not None
                ):
                    return True
    return False


def coerce_legacy_wait_at_to_whisper_rows(
    spec: dict[str, Any],
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace legacy ``wait_at`` with ``wait_word`` when ``words`` exist; otherwise drop ``wait_at``."""
    _ = segments

    def _apply_rows(rs: list[Any]) -> None:
        for row in rs:
            if not isinstance(row, dict):
                continue
            if row.get("wait_at") is None:
                continue
            t = float(row["wait_at"])
            if isinstance(words, list) and words:
                boxes = row.get("boxes")
                if isinstance(boxes, list) and boxes and isinstance(boxes[0], dict):
                    boxes[0]["wait_word"] = wait_word_index_for_time(words, t)
            row.pop("wait_at", None)

    out = dict(spec)
    if out.get("pages") is not None:
        new_pages: list[Any] = []
        for page in out["pages"]:
            p = dict(page) if isinstance(page, dict) else page
            if isinstance(p, dict) and isinstance(p.get("rows"), list):
                p["rows"] = [dict(r) if isinstance(r, dict) else r for r in p["rows"]]
                _apply_rows(p["rows"])
            new_pages.append(p)
        out["pages"] = new_pages
    elif isinstance(out.get("rows"), list):
        out["rows"] = [dict(r) if isinstance(r, dict) else r for r in out["rows"]]
        _apply_rows(out["rows"])
    return out


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
    # Document-frequent tokens are weak merge signals (appear in many sentences).
    per_sent = [content_tokens(s) for s in sentences]
    df: dict[str, int] = {}
    for toks in per_sent:
        for w in toks:
            df[w] = df.get(w, 0) + 1
    n = len(sentences)
    glue = {w for w, c in df.items() if c >= max(3, (n + 1) // 2)}

    beats: list[list[str]] = []
    for i, sent in enumerate(sentences):
        toks = per_sent[i]
        if not beats:
            beats.append([sent])
            continue
        prev_toks = per_sent[i - 1]
        if not toks or not prev_toks:
            beats.append([sent])
            continue
        shared = (toks & prev_toks) - glue
        union = (toks | prev_toks) - glue
        jacc = (len(shared) / len(union)) if union else 0.0
        if shared or jacc >= jaccard_threshold:
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

    uncovered: list[str] = []
    for i, beat in enumerate(beats, start=1):
        if not any(label_covers_beat(lab, beat) for lab in labels):
            preview = beat if len(beat) <= 72 else beat[:69] + "..."
            uncovered.append(f"beat {i}: {preview}")

    allowed_uncovered = max(0, slack)
    if len(uncovered) > allowed_uncovered:
        shown = "; ".join(uncovered[:5])
        more = f" (+{len(uncovered) - 5} more)" if len(uncovered) > 5 else ""
        note = (
            f" ({len(uncovered)} uncovered; allow ≤{allowed_uncovered} after retry)"
            if slack
            else f" ({len(uncovered)} of {len(beats)} beats uncovered)"
        )
        issues.append(
            f"subject-beat coverage failed{note}: {shown}{more}. "
            "Add a spoken-phrase label for each new topic; keep the same board while "
            "sentences elaborate the same subject."
        )

    narr_toks = content_tokens(narration_text)
    invented = [
        lab
        for lab in labels
        if content_tokens(lab) and not (content_tokens(lab) & narr_toks)
    ]
    if invented:
        sample = ", ".join(repr(x) for x in invented[:6])
        more = f" (+{len(invented) - 6} more)" if len(invented) > 6 else ""
        issues.append(
            f"labels not spoken in narration (invented diagram terms): {sample}{more}"
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
    if layout is not None and not isinstance(layout, dict):
        layout = {}
    elif layout is None:
        layout = {}

    try:
        budget = layout_stack_budget(title, layout)
    except (TypeError, ValueError):
        return []
    row_gap = float(layout.get("row_gap", 0.6))
    col_gap = float(layout.get("column_gap", 0.8))

    issues: list[str] = []
    pages = _spec_pages_rows(spec)
    for pi, rows in enumerate(pages):
        row_heights: list[float] = []
        row_widths: list[float] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            boxes = row.get("boxes")
            if not isinstance(boxes, list) or not boxes:
                continue
            try:
                hs = [float(b["height"]) for b in boxes if isinstance(b, dict)]
                ws = [float(b["width"]) for b in boxes if isinstance(b, dict)]
                if not hs or not ws:
                    continue
                row_heights.append(max(hs))
                rw = sum(ws)
                if len(ws) > 1:
                    rw += col_gap * (len(ws) - 1)
                row_widths.append(rw)
            except (KeyError, TypeError, ValueError):
                continue
        stack_h = (
            sum(row_heights) + (len(row_heights) - 1) * row_gap if row_heights else 0.0
        )
        max_rw = max(row_widths) if row_widths else 0.0
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


def _validate_image_element(box: dict[str, Any], *, bp: str) -> None:
    img = box.get("image")
    if not isinstance(img, str) or not img.strip():
        raise SceneSpecError(f"{bp}: image must be a non-empty bundle-relative path string")
    p = Path(img.strip())
    if p.is_absolute() or ".." in p.parts:
        raise SceneSpecError(
            f"{bp}: image path must be relative to the bundle directory (no absolute paths or '..')"
        )
    for fld in ("width", "height"):
        if fld not in box:
            raise SceneSpecError(f"{bp}: missing {fld}")
        v = box[fld]
        if not isinstance(v, (int, float)) or v <= 0:
            raise SceneSpecError(f"{bp}: {fld} must be a positive number")
    for fld in ("color", "font_size"):
        if fld in box:
            raise SceneSpecError(
                f"{bp}: {fld} is not allowed on an image element (only label boxes take {fld})"
            )
    prompt = box.get("prompt")
    if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
        raise SceneSpecError(f"{bp}: prompt must be a non-empty string if set")
    lab = box.get("label")
    if lab is not None and not isinstance(lab, str):
        raise SceneSpecError(f"{bp}: label must be a string if set (used as timing anchor only)")


def _validate_pace_field(obj: dict[str, Any], *, path: str) -> None:
    if "pace" not in obj or obj.get("pace") is None:
        return
    val = str(obj.get("pace")).strip().lower()
    if val != "none":
        raise SceneSpecError(f"{path}: pace must be 'none' if set (opt out of beat sync)")


def _validate_row_list(rows: list[Any], *, path_label: str, prefix: str) -> None:
    for i, row in enumerate(rows):
        rp = f"{path_label}: {prefix}[{i}]"
        if not isinstance(row, dict):
            raise SceneSpecError(f"{rp}: row must be a mapping")
        if "boxes" not in row:
            raise SceneSpecError(f"{rp}: missing boxes")
        boxes = row["boxes"]
        if not isinstance(boxes, list) or not boxes:
            raise SceneSpecError(f"{rp}: boxes must be a non-empty list")
        if "run_time" not in row:
            raise SceneSpecError(f"{rp}: run_time is required")
        rt = row["run_time"]
        if not isinstance(rt, (int, float)) or rt <= 0:
            raise SceneSpecError(f"{rp}: run_time must be a positive number")
        _validate_pace_field(row, path=rp)
        ws = row.get("wait_segment")
        if ws is not None and (not isinstance(ws, int) or ws < 0):
            raise SceneSpecError(f"{rp}: wait_segment must be a non-negative int or null")
        ww = row.get("wait_word")
        if ww is not None and (not isinstance(ww, int) or ww < 0):
            raise SceneSpecError(f"{rp}: wait_word must be a non-negative int or null")
        if ws is not None and ww is not None:
            raise SceneSpecError(
                f"{rp}: set at most one of wait_segment and wait_word (prefer wait_word for word timestamps)"
            )
        if row.get("wait_at") is not None:
            raise SceneSpecError(
                f"{rp}: wait_at is not allowed — use wait_word (``timing.json`` ``words`` index); "
                f"re-run `docgen scene-compile` after `docgen timestamps`."
            )

        box_pacing = False
        for j, box in enumerate(boxes):
            bp = f"{rp}: boxes[{j}]"
            if not isinstance(box, dict):
                raise SceneSpecError(f"{bp}: box must be a mapping")
            _validate_pace_field(box, path=bp)
            if box.get("wait_segment") is not None:
                raise SceneSpecError(
                    f"{bp}: wait_segment on a box is not supported — use ``wait_word`` on the box, "
                    f"or ``wait_segment`` on the row for legacy upgrade."
                )
            bww = box.get("wait_word")
            if bww is not None and (not isinstance(bww, int) or bww < 0):
                raise SceneSpecError(f"{bp}: wait_word must be a non-negative int or null")
            if bww is not None:
                box_pacing = True
            if _is_image_element(box):
                _validate_image_element(box, bp=bp)
                continue
            for fld in ("label", "color", "width", "height", "font_size"):
                if fld not in box:
                    raise SceneSpecError(f"{bp}: missing {fld}")
            if str(box["color"]) not in ALLOWED_COLORS:
                raise SceneSpecError(
                    f"{bp}: color must be one of {sorted(ALLOWED_COLORS)}"
                )
            for num_f in ("width", "height", "font_size"):
                v = box[num_f]
                if not isinstance(v, (int, float)) or v <= 0:
                    raise SceneSpecError(f"{bp}: {num_f} must be a positive number")
            bsub = box.get("subtitle")
            if bsub is not None:
                if not isinstance(bsub, str):
                    raise SceneSpecError(f"{bp}: subtitle must be a string if set")
                if len(bsub.strip()) > 60:
                    raise SceneSpecError(f"{bp}: subtitle must be at most 60 characters")
            shape = box.get("shape")
            if shape is not None and str(shape).strip().lower() not in ALLOWED_SHAPES:
                raise SceneSpecError(
                    f"{bp}: shape must be one of {sorted(ALLOWED_SHAPES)} if set"
                )
            reveal = box.get("reveal")
            if reveal is not None and str(reveal).strip().lower() not in ALLOWED_REVEALS:
                raise SceneSpecError(
                    f"{bp}: reveal must be one of {sorted(ALLOWED_REVEALS)} if set"
                )
            emphasis = box.get("emphasis")
            if emphasis is not None and str(emphasis).strip().lower() not in ALLOWED_EMPHASIS:
                raise SceneSpecError(
                    f"{bp}: emphasis must be one of {sorted(ALLOWED_EMPHASIS)} if set"
                )

        has_row_pacing = row.get("wait_word") is not None or row.get("wait_segment") is not None
        if has_row_pacing and box_pacing:
            raise SceneSpecError(
                f"{rp}: set pacing on the row (``wait_word`` / ``wait_segment``) "
                f"**or** on boxes (``wait_word`` per box), not both"
            )


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
            raise SceneSpecError(
                f"{ep}: from={src!r} is ambiguous (duplicate labels on this page)"
            )
        if labels[dst] > 1:
            raise SceneSpecError(
                f"{ep}: to={dst!r} is ambiguous (duplicate labels on this page)"
            )
        if src == dst:
            raise SceneSpecError(f"{ep}: from and to must differ")
        col = edge.get("color")
        if col is not None and str(col) not in ALLOWED_COLORS:
            raise SceneSpecError(
                f"{ep}: color must be one of {sorted(ALLOWED_COLORS)} if set"
            )
        style = edge.get("style")
        if style is not None and str(style).strip().lower() not in ALLOWED_EDGE_STYLES:
            raise SceneSpecError(
                f"{ep}: style must be one of {sorted(ALLOWED_EDGE_STYLES)} if set"
            )
        label = edge.get("label")
        if label is not None:
            if not isinstance(label, str):
                raise SceneSpecError(f"{ep}: label must be a string if set")
            if len(label.strip()) > 40:
                raise SceneSpecError(f"{ep}: label must be at most 40 characters")


def validate_scene_spec(data: dict[str, Any], *, path_label: str = "spec") -> None:
    for k in SPEC_REQUIRED_TOP:
        if k not in data:
            raise SceneSpecError(f"{path_label}: missing required key {k!r}")
    sid = data["segment_id"]
    if not isinstance(sid, str) or not sid.strip():
        raise SceneSpecError(f"{path_label}: segment_id must be a non-empty string")
    cname = data["class_name"]
    if not isinstance(cname, str) or not cname.strip():
        raise SceneSpecError(f"{path_label}: class_name must be a non-empty string")

    tk = data.get("timing_key")
    if tk is not None and (not isinstance(tk, str) or not tk.strip()):
        raise SceneSpecError(f"{path_label}: timing_key must be a non-empty string if set")

    title = data["title"]
    if not isinstance(title, dict):
        raise SceneSpecError(f"{path_label}: title must be a mapping")
    for fld in ("text", "font_size", "color"):
        if fld not in title:
            raise SceneSpecError(f"{path_label}: title.{fld} is required")
    if str(title["color"]) not in ALLOWED_COLORS:
        raise SceneSpecError(
            f"{path_label}: title.color must be one of {sorted(ALLOWED_COLORS)}"
        )
    tsub = title.get("subtitle")
    if tsub is not None:
        if not isinstance(tsub, str):
            raise SceneSpecError(f"{path_label}: title.subtitle must be a string if set")
        if len(tsub.strip()) > 80:
            raise SceneSpecError(f"{path_label}: title.subtitle must be at most 80 characters")

    has_pages = data.get("pages") is not None
    has_rows = data.get("rows") is not None
    if has_pages == has_rows:
        raise SceneSpecError(
            f"{path_label}: set exactly one of 'rows' (single page) or 'pages' (multi-page)"
        )

    layout = data.get("layout") or {}
    if layout and not isinstance(layout, dict):
        raise SceneSpecError(f"{path_label}: layout must be a mapping if present")

    pt = layout.get("page_transition", "fade")
    if str(pt) not in ALLOWED_PAGE_TRANSITIONS:
        raise SceneSpecError(
            f"{path_label}: layout.page_transition must be one of {sorted(ALLOWED_PAGE_TRANSITIONS)}"
        )
    ptrt = layout.get("page_transition_run_time", 0.45)
    if not isinstance(ptrt, (int, float)) or not (0 < float(ptrt) <= 5.0):
        raise SceneSpecError(
            f"{path_label}: layout.page_transition_run_time must be a number in (0, 5] if set"
        )
    dwell_mode = layout.get("dwell_emphasis", "auto")
    if str(dwell_mode).strip().lower() not in ALLOWED_DWELL_EMPHASIS:
        raise SceneSpecError(
            f"{path_label}: layout.dwell_emphasis must be one of "
            f"{sorted(ALLOWED_DWELL_EMPHASIS)} if set"
        )
    if "dwell_run_time" in layout:
        drt = layout.get("dwell_run_time")
        if not isinstance(drt, (int, float)) or not (0 < float(drt) <= 3.0):
            raise SceneSpecError(
                f"{path_label}: layout.dwell_run_time must be a number in (0, 3] if set"
            )

    if has_rows:
        rows = data["rows"]
        if not isinstance(rows, list) or not rows:
            raise SceneSpecError(f"{path_label}: rows must be a non-empty list")
        _validate_row_list(rows, path_label=path_label, prefix="rows")
        _validate_edges(
            data.get("edges"),
            labels=_page_box_labels(rows),
            path_label=path_label,
        )
        return

    if data.get("edges") is not None:
        raise SceneSpecError(
            f"{path_label}: top-level edges are only valid with rows; "
            f"put edges on each page for multi-page specs"
        )

    pages = data["pages"]
    if not isinstance(pages, list) or not pages:
        raise SceneSpecError(f"{path_label}: pages must be a non-empty list")
    for pi, page in enumerate(pages):
        pp = f"{path_label}: pages[{pi}]"
        if not isinstance(page, dict):
            raise SceneSpecError(f"{pp}: page must be a mapping")
        if "rows" not in page:
            raise SceneSpecError(f"{pp}: missing rows")
        pr = page["rows"]
        if not isinstance(pr, list) or not pr:
            raise SceneSpecError(f"{pp}: rows must be a non-empty list")
        _validate_row_list(pr, path_label=path_label, prefix=f"pages[{pi}].rows")
        _validate_edges(
            page.get("edges"),
            labels=_page_box_labels(pr),
            path_label=pp,
        )
        if pi > 0:
            ptx = page.get("transition", pt)
            if str(ptx) not in ALLOWED_PAGE_TRANSITIONS:
                raise SceneSpecError(
                    f"{pp}: transition must be one of {sorted(ALLOWED_PAGE_TRANSITIONS)} if set"
                )


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

    class_name = str(spec["class_name"]).strip()
    timing_key = spec.get("timing_key")
    if not timing_key or not str(timing_key).strip():
        raise SceneSpecError(
            "timing_key is required (narration stem, e.g. 01-overview) — "
            "set in YAML or pass after resolving segment_names in docgen.yaml"
        )
    timing_key = str(timing_key).strip()

    title = spec["title"]
    title_text: str = str(title["text"])
    title_fs = int(title["font_size"])
    title_color = str(title["color"])
    title_subtitle = str(title.get("subtitle") or "").strip()

    layout = spec.get("layout") or {}
    first_row_title_buff = float(layout.get("first_row_title_buff", 0.5))
    row_gap = float(layout.get("row_gap", 0.6))
    column_gap = float(layout.get("column_gap", 0.8))
    page_tr_run = float(layout.get("page_transition_run_time", 0.45))

    pages = _normalized_pages(spec)
    if _any_wait_segment_in_pages(pages):
        raise SceneSpecError(
            "wait_segment is not supported in compiled scenes — use wait_word (timing.json "
            "`words` index) only. Run `docgen scene-compile` so rows are upgraded from Whisper "
            "words, or edit the YAML to use wait_word."
        )

    # Per-box clamped run_time / page fade when Whisper words are available.
    reveal_by_key: dict[tuple[int, int, int], RevealEvent] = {}
    if words:
        for ev in simulate_reveal_timeline(spec, words, clamp_run_times=True):
            reveal_by_key[(ev.page, ev.row, ev.box)] = ev

    title_rt = TITLE_WRITE_RUN_TIME
    lines: list[str] = [
        f"class {class_name}(_TimedScene):",
        "    def construct(self):",
        "        self.camera.background_color = C_BG",
        f"        timing_words = _load_timing_words({timing_key!r})",
        "",
    ]
    if title_subtitle:
        sub_fs = max(14, title_fs - 10)
        lines.extend(
            [
                f"        _title_main = Text({title_text!r}, font_size={title_fs}, color={title_color})",
                f"        _title_sub = Text({title_subtitle!r}, font_size={sub_fs}, color={title_color})",
                "        _title_sub.set_opacity(0.85)",
                "        title = VGroup(_title_main, _title_sub).arrange(DOWN, buff=0.12).to_edge(UP)",
                f"        self.timed_play(Write(title), run_time={title_rt})",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"        title = Text({title_text!r}, font_size={title_fs}, color={title_color}).to_edge(UP)",
                f"        self.timed_play(Write(title), run_time={title_rt})",
                "",
            ]
        )

    # Map (page, later-box-var) → list of (edge_var, anim) where anim is grow|fade.
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]] = {}
    page_edge_vars: dict[int, list[str]] = {}

    for p, page in enumerate(pages):
        rows = page["rows"]
        page_has_image = any(
            _is_image_element(box)
            for row in rows
            for box in (row.get("boxes") or [])
        )
        for r, row in enumerate(rows):
            boxes_raw = row["boxes"]
            for b, box in enumerate(boxes_raw):
                var = f"_bx_{p}_{r}_{b}"
                w = float(box["width"])
                h = float(box["height"])
                if _is_image_element(box):
                    rel = str(box["image"]).strip()
                    lines.append(
                        f"        {var} = _image({rel!r}, {w}, {h})"
                    )
                    continue
                lines.append(_box_ctor_line(var, box))

        for r, row in enumerate(rows):
            boxes_raw = row["boxes"]
            box_names = [f"_bx_{p}_{r}_{b}" for b in range(len(boxes_raw))]
            row_var = f"_row_{p}_{r}"
            # ImageMobject is not a VMobject, so any row (and its page stack)
            # containing an image element must use Group instead of VGroup.
            container = "Group" if page_has_image else "VGroup"
            if len(box_names) == 1:
                lines.append(f"        {row_var} = {container}({box_names[0]})")
            else:
                joined = ", ".join(box_names)
                lines.append(
                    f"        {row_var} = {container}({joined}).arrange(RIGHT, buff={column_gap})"
                )

        row_refs = ", ".join(f"_row_{p}_{r}" for r in range(len(rows)))
        stack_var = f"_p{p}_stack"
        stack_container = "Group" if page_has_image else "VGroup"
        lines.append(
            f"        {stack_var} = {stack_container}({row_refs}).arrange(DOWN, buff={row_gap}, center=True)"
        )
        lines.append(
            f"        {stack_var}.next_to(title, DOWN, buff={first_row_title_buff})"
        )

        # Build edge arrows after layout so endpoints use final positions.
        label_vars = _box_var_by_label(p, rows)
        for ei, edge in enumerate(page.get("edges") or []):
            if not isinstance(edge, dict):
                continue
            src = str(edge["from"]).strip()
            dst = str(edge["to"]).strip()
            src_var = label_vars.get(src)
            dst_var = label_vars.get(dst)
            if not src_var or not dst_var:
                continue
            evar = f"_ar_{p}_{ei}"
            ecol = str(edge.get("color") or "C_ACCENT")
            estyle = str(edge.get("style") or "solid").strip().lower() or "solid"
            elabel = str(edge.get("label") or "").strip()
            lines.append(
                f"        {evar} = _arrow({src_var}, {dst_var}, {ecol}, style={estyle!r})"
            )
            page_edge_vars.setdefault(p, []).append(evar)
            # Reveal with the later endpoint (second in box creation order).
            order = {v: i for i, v in enumerate(label_vars.values())}
            later = dst_var if order.get(dst_var, 0) >= order.get(src_var, 0) else src_var
            # GrowArrow only works on solid Arrow; dashed / labeled edges FadeIn.
            anim = "grow" if estyle == "solid" and not elabel else "fade"
            edges_with_target.setdefault((p, later), []).append((evar, anim))
            if elabel:
                lvar = f"{evar}_lbl"
                lines.append(
                    f"        {lvar} = Text({elabel!r}, font_size=16, color={ecol})"
                )
                lines.append(
                    f"        {lvar}.move_to({evar}.get_center()).shift(UP * 0.22)"
                )
                page_edge_vars.setdefault(p, []).append(lvar)
                edges_with_target.setdefault((p, later), []).append((lvar, "fade"))

    lines.append("")

    # Box vars per page — page transitions FadeOut these individually. Fading the
    # parent VGroup can re-add unrevealed siblings at full opacity (flash dump).
    page_box_vars: dict[int, list[str]] = {}
    for p, page in enumerate(pages):
        for r, row in enumerate(page["rows"]):
            boxes_raw = row.get("boxes") or []
            if not isinstance(boxes_raw, list):
                continue
            for b_idx, box in enumerate(boxes_raw):
                if isinstance(box, dict):
                    page_box_vars.setdefault(p, []).append(f"_bx_{p}_{r}_{b_idx}")

    for p, page in enumerate(pages):
        for r, row in enumerate(page["rows"]):
            boxes_raw = row["boxes"]
            if not isinstance(boxes_raw, list):
                continue
            row_run_time = float(row["run_time"])
            row_ww = row.get("wait_word")
            for b_idx, box in enumerate(boxes_raw):
                if not isinstance(box, dict):
                    continue
                ev = reveal_by_key.get((p, r, b_idx))
                run_time = (
                    round(float(ev.run_time), 3) if ev is not None else row_run_time
                )
                page_fade_rt = (
                    round(float(ev.page_fade_out), 3)
                    if ev is not None
                    else page_tr_run
                )
                ww = box.get("wait_word")
                if ww is None and b_idx == 0 and row_ww is not None:
                    ww = row_ww
                if ww is not None:
                    lines.append(
                        f"        self.wait_until_word(timing_words, {int(ww)})"
                    )
                if p > 0 and r == 0 and b_idx == 0:
                    trans = page.get("transition")
                    prev_boxes = page_box_vars.get(p - 1) or []
                    prev_edges = page_edge_vars.get(p - 1) or []
                    fade_targets = prev_boxes + prev_edges
                    if trans == "fade":
                        if fade_targets:
                            fade_args = ", ".join(f"FadeOut({t})" for t in fade_targets)
                            lines.append(
                                f"        self.timed_play({fade_args}, "
                                f"run_time={page_fade_rt})"
                            )
                        else:
                            lines.append(f"        self.timed_wait({page_fade_rt})")
                    elif trans == "none":
                        for t in fade_targets:
                            lines.append(f"        self.remove({t})")
                        lines.append("        self.timed_wait(0.05)")
                bx = f"_bx_{p}_{r}_{b_idx}"
                reveal = (
                    str(ev.reveal)
                    if ev is not None
                    else str(box.get("reveal") or "fade").strip().lower()
                )
                reveal_part = _reveal_anim(bx, reveal)
                edge_anims = edges_with_target.get((p, bx), [])
                parts = [reveal_part]
                for evar, kind in edge_anims:
                    if kind == "grow":
                        parts.append(f"GrowArrow({evar})")
                    else:
                        parts.append(f"FadeIn({evar})")
                anims = ", ".join(parts)
                lines.append(
                    f"        self.timed_play({anims}, run_time={run_time})"
                )
                dwell_rt = float(ev.dwell_run_time) if ev is not None else 0.0
                emphasis = str(ev.emphasis) if ev is not None else "none"
                emph = _emphasis_anim(bx, emphasis)
                if emph and dwell_rt >= MIN_DWELL_RUN_TIME:
                    lines.append(
                        f"        self.timed_play({emph}, run_time={round(dwell_rt, 3)})"
                    )

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

    return "\n".join(lines) + "\n"
