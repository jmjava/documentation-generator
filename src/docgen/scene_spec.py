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
* Uses the shared ``_box`` helper (text centered in the rounded rect).

Typical workflow:

1. ``docgen scene-spec-generate --segment <id> --config docgen.yaml`` (YAML under ``animations/specs/``),
   or author ``animations/specs/<stem>.scene.yaml`` by hand.
2. ``docgen scene-compile path/to/spec.scene.yaml --config docgen.yaml`` (if not using ``--compile``).
3. ``docgen timestamps`` → ``docgen manim`` as usual.

``docgen scene-spec-generate`` also runs :func:`layout_budget_violations` so generated YAML
must fit the dogfood frame; ``scene-compile`` does not apply that check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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

SPEC_REQUIRED_TOP = ("segment_id", "class_name", "title")

# Match ``scenes.py`` dogfood header: frame width × height in Manim units.
FRAME_WIDTH = 14.22
FRAME_HEIGHT = 8.0
# Horizontal band left clear of rounded boxes at edge; vertical margin above y = -4.
_LAYOUT_HORIZONTAL_SAFE = FRAME_WIDTH - 1.0
_LAYOUT_BOTTOM_MARGIN = 0.55


def _title_band_estimate(font_size: int) -> float:
    """Rough vertical space from top of frame through title and first gap."""
    fs = max(14, int(font_size))
    return 0.78 + (fs / 36.0) * 0.52


def layout_stack_budget(title: dict[str, Any], layout: dict[str, Any] | None) -> float:
    """Max total row-stack height (Manim units) that fits below ``title`` without clipping."""
    layout = layout or {}
    buff = float(layout.get("first_row_title_buff", 0.5))
    fs = title.get("font_size")
    if not isinstance(fs, (int, float)):
        fs = 36
    band = _title_band_estimate(int(fs))
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

    Uses the same label/word token rules as before. Each matched box waits at **word**
    ``start``, not segment boundary. Row-level ``wait_word`` / ``wait_segment`` are cleared
    when ``overwrite=True`` (compile path); legacy row ``wait_word`` is seeded onto the first
    box only if that box has no label match.
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
        tokens = [_normalize_word(t) for t in str(label).split() if _normalize_word(t)]
        if not tokens:
            return None
        n = len(word_stream)
        m = len(tokens)
        i = from_idx
        while i <= n - m:
            ok = True
            for k in range(m):
                if not _tokens_match(tokens[k], word_stream[i + k][0]):
                    ok = False
                    break
            if ok:
                return (i + m - 1, word_stream[i][2])
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

            legacy_rw = row.pop("wait_word", None) if overwrite else None
            if overwrite:
                row.pop("wait_segment", None)

            for bi, box in enumerate(boxes):
                if not isinstance(box, dict):
                    continue
                box.pop("wait_at", None)
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
                elif overwrite and bi == 0 and legacy_rw is not None:
                    box["wait_word"] = int(legacy_rw)
                elif overwrite:
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
    validate_scene_spec(data, path_label=str(path))
    return data


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

        has_row_pacing = row.get("wait_word") is not None or row.get("wait_segment") is not None
        if has_row_pacing and box_pacing:
            raise SceneSpecError(
                f"{rp}: set pacing on the row (``wait_word`` / ``wait_segment``) "
                f"**or** on boxes (``wait_word`` per box), not both"
            )


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

    if has_rows:
        rows = data["rows"]
        if not isinstance(rows, list) or not rows:
            raise SceneSpecError(f"{path_label}: rows must be a non-empty list")
        _validate_row_list(rows, path_label=path_label, prefix="rows")
        return

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
        if pi > 0:
            ptx = page.get("transition", pt)
            if str(ptx) not in ALLOWED_PAGE_TRANSITIONS:
                raise SceneSpecError(
                    f"{pp}: transition must be one of {sorted(ALLOWED_PAGE_TRANSITIONS)} if set"
                )


def _normalized_pages(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return page dicts with keys rows, transition (None for first page only)."""
    layout = spec.get("layout") or {}
    default_tr = str(layout.get("page_transition", "fade"))
    if spec.get("pages") is not None:
        pages_raw = spec["pages"]
        assert isinstance(pages_raw, list)
        out: list[dict[str, Any]] = []
        for pi, page in enumerate(pages_raw):
            tr = None if pi == 0 else str(page.get("transition", default_tr))
            out.append({"rows": page["rows"], "transition": tr})
        return out
    return [{"rows": spec["rows"], "transition": None}]


def _any_wait_segment_in_pages(pages: list[dict[str, Any]]) -> bool:
    for page in pages:
        for row in page["rows"]:
            if row.get("wait_segment") is not None:
                return True
    return False


def compile_scene_class(spec: dict[str, Any]) -> str:
    """Return a full ``class Name(_TimedScene): ...`` definition (no imports).

    ``spec`` must include ``timing_key`` (narration audio stem for ``timing.json``),
    either in the mapping or merged by the caller from ``Config.resolve_segment_name``.
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

    lines: list[str] = [
        f"class {class_name}(_TimedScene):",
        "    def construct(self):",
        "        self.camera.background_color = C_BG",
        f"        timing_words = _load_timing_words({timing_key!r})",
        "",
        f"        title = Text({title_text!r}, font_size={title_fs}, color={title_color}).to_edge(UP)",
        "        self.timed_play(Write(title), run_time=2.0)",
        "",
    ]

    for p, page in enumerate(pages):
        rows = page["rows"]
        for r, row in enumerate(rows):
            boxes_raw = row["boxes"]
            for b, box in enumerate(boxes_raw):
                var = f"_bx_{p}_{r}_{b}"
                lab = str(box["label"])
                col = str(box["color"])
                w = float(box["width"])
                h = float(box["height"])
                fs = int(box["font_size"])
                lines.append(
                    f"        {var} = _box({lab!r}, {col}, {w}, {h}, {fs})"
                )

        for r, row in enumerate(rows):
            boxes_raw = row["boxes"]
            box_names = [f"_bx_{p}_{r}_{b}" for b in range(len(boxes_raw))]
            row_var = f"_row_{p}_{r}"
            if len(box_names) == 1:
                lines.append(f"        {row_var} = VGroup({box_names[0]})")
            else:
                joined = ", ".join(box_names)
                lines.append(
                    f"        {row_var} = VGroup({joined}).arrange(RIGHT, buff={column_gap})"
                )

        row_refs = ", ".join(f"_row_{p}_{r}" for r in range(len(rows)))
        stack_var = f"_p{p}_stack"
        lines.append(
            f"        {stack_var} = VGroup({row_refs}).arrange(DOWN, buff={row_gap}, center=True)"
        )
        lines.append(
            f"        {stack_var}.next_to(title, DOWN, buff={first_row_title_buff})"
        )

    lines.append("")

    for p, page in enumerate(pages):
        for r, row in enumerate(page["rows"]):
            boxes_raw = row["boxes"]
            if not isinstance(boxes_raw, list):
                continue
            run_time = float(row["run_time"])
            row_ww = row.get("wait_word")
            for b_idx, box in enumerate(boxes_raw):
                if not isinstance(box, dict):
                    continue
                ww = box.get("wait_word")
                if ww is None and b_idx == 0 and row_ww is not None:
                    ww = row_ww
                if ww is not None:
                    lines.append(
                        f"        self.wait_until_word(timing_words, {int(ww)})"
                    )
                if p > 0 and r == 0 and b_idx == 0:
                    trans = page.get("transition")
                    if trans == "fade":
                        prev_stack = f"_p{p - 1}_stack"
                        lines.append(
                            f"        self.timed_play(FadeOut({prev_stack}), run_time={page_tr_run})"
                        )
                    elif trans == "none":
                        prev_stack = f"_p{p - 1}_stack"
                        lines.append(f"        self.remove({prev_stack})")
                        lines.append("        self.timed_wait(0.05)")
                lines.append(
                    f"        self.timed_play(FadeIn(_bx_{p}_{r}_{b_idx}), run_time={run_time})"
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
