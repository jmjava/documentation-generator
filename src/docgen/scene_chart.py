"""Paced bar and line charts as a page alternative to diagram rows.

A page sets ``chart`` instead of ``rows``. Each series item is one reveal:
a bar grows from the left, or a line point fades in and the segment from the
previous point is drawn. Digits of each ``value`` must appear in the narration
(``12`` matches; the word "twelve" does not).
"""

from __future__ import annotations

import math
import re
from typing import Any

from docgen.manim_primitives import ALLOWED_EMPHASIS

_CHART_KINDS = frozenset({"bar", "line"})
_CHART_COLORS = ("C_GREEN", "C_BLUE", "C_ORANGE", "C_TEAL", "C_PURPLE", "C_ACCENT")
_CHART_KEYS = frozenset({"kind", "series"})
_SERIES_KEYS = frozenset({"label", "value", "color", "wait_word", "pace", "emphasis"})
_MAX_SERIES = 6
_BAR_HEIGHT = 0.36
_BAR_MIN = 0.45
_BAR_SPAN = 5.8
_PLOT_LEFT = -4.2
_PLOT_SPAN = 8.4
_PLOT_HEIGHT = 2.6


def _fail(message: str) -> None:
    from docgen.scene_spec import SceneSpecError

    raise SceneSpecError(message)


def page_has_chart(page: Any) -> bool:
    """True when a page mapping authors a chart instead of diagram rows."""
    return isinstance(page, dict) and "chart" in page


def uses_chart(spec: dict[str, Any]) -> bool:
    """True after materialize when a page's boxes are chart series."""
    if not isinstance(spec, dict):
        return False
    pages = spec.get("pages")
    if not isinstance(pages, list):
        return False
    return any(_page_is_chart_boxes(page) for page in pages)


def _page_is_chart_boxes(page: Any) -> bool:
    if not isinstance(page, dict):
        return False
    rows = page.get("rows")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return False
    boxes = rows[0].get("boxes")
    if not isinstance(boxes, list) or not boxes or not isinstance(boxes[0], dict):
        return False
    return bool(boxes[0].get("chart_kind"))


def materialize_charts(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose chart pages are rows of paced series boxes.

    Specs with no ``chart`` page are returned unchanged. The copy is what
    compile, beat sync, and label coverage walk; on-disk YAML keeps ``chart``.
    """
    if not _spec_has_chart(spec):
        return spec
    out = dict(spec)
    pages = spec.get("pages")
    out["pages"] = [_expand_page(page, i) for i, page in enumerate(pages)]
    return out


def _spec_has_chart(spec: dict[str, Any]) -> bool:
    if not isinstance(spec, dict):
        return False
    pages = spec.get("pages")
    if not isinstance(pages, list):
        return False
    return any(page_has_chart(page) for page in pages)


def _expand_page(page: Any, index: int) -> Any:
    if not page_has_chart(page):
        return page
    path = f"pages[{index}]"
    if "rows" in page:
        _fail(f"{path}: set rows or chart, not both")
    if "edges" in page:
        _fail(f"{path}: chart pages do not take edges")
    rows = _chart_rows(page.get("chart"), path)[1]
    out: dict[str, Any] = {"rows": rows}
    if "transition" in page:
        out["transition"] = page["transition"]
    return out


def _chart_rows(chart: Any, path: str) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(chart, dict):
        _fail(f"{path}.chart: must be a mapping")
    _reject_unknown(chart, _CHART_KEYS, f"{path}.chart")
    kind = str(chart.get("kind") or "").strip().lower()
    if kind not in _CHART_KINDS:
        _fail(f"{path}.chart.kind: must be bar or line")
    series = chart.get("series")
    if not isinstance(series, list) or not series:
        _fail(f"{path}.chart.series: must be a non-empty list")
    if len(series) > _MAX_SERIES:
        _fail(f"{path}.chart.series: at most {_MAX_SERIES} items fit on one page")
    return kind, _series_rows(series, kind, f"{path}.chart.series")


def _reject_unknown(mapping: dict[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        _fail(f"{path}: unknown keys {unknown}")


def _series_rows(
    series: list[Any], kind: str, path: str
) -> list[dict[str, Any]]:
    peak = _series_peak(series, path)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(series):
        box = _series_box(item, index, kind, peak, path)
        label = str(box["label"])
        if label in seen:
            _fail(f"{path}[{index}]: duplicate label {label!r}")
        seen.add(label)
        rows.append({"run_time": 0.55, "boxes": [box]})
    return rows


def _series_peak(series: list[Any], path: str) -> float:
    values: list[float] = []
    for index, item in enumerate(series):
        if not isinstance(item, dict):
            _fail(f"{path}[{index}]: series item must be a mapping")
        values.append(_positive_value(item.get("value"), f"{path}[{index}]"))
    return max(values)


def _positive_value(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{path}.value: must be a positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        _fail(f"{path}.value: must be a positive finite number")
    return number


def _series_box(
    item: Any, index: int, kind: str, peak: float, path: str
) -> dict[str, Any]:
    loc = f"{path}[{index}]"
    if not isinstance(item, dict):
        _fail(f"{loc}: series item must be a mapping")
    _reject_unknown(item, _SERIES_KEYS, loc)
    value = _positive_value(item.get("value"), loc)
    box: dict[str, Any] = {
        "label": _series_label(item.get("label"), loc),
        "color": _series_color(item.get("color"), index, loc),
        "width": 2.2,
        "height": _BAR_HEIGHT,
        "font_size": 22,
        "chart_kind": kind,
        "value": value,
        "value_text": _value_token(value),
        "bar_width": _bar_width(value, peak),
    }
    _copy_optional_series_fields(item, box, loc)
    return box


def _series_label(label: Any, loc: str) -> str:
    if not isinstance(label, str) or not str(label).strip():
        _fail(f"{loc}.label: must be a non-empty string")
    text = str(label).strip()
    if len(text) > 40:
        _fail(f"{loc}.label: must be at most 40 characters")
    return text


def _series_color(color: Any, index: int, loc: str) -> str:
    if color is None:
        return _CHART_COLORS[index % len(_CHART_COLORS)]
    from docgen.scene_spec import ALLOWED_COLORS

    token = str(color).strip()
    if token not in ALLOWED_COLORS:
        _fail(f"{loc}.color: must be one of {sorted(ALLOWED_COLORS)}")
    return token


def _value_token(value: float) -> str:
    if value == int(value) and abs(value) < 1e12:
        return str(int(value))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _bar_width(value: float, peak: float) -> float:
    return round(_BAR_MIN + _BAR_SPAN * (value / peak), 3)


def _copy_optional_series_fields(
    item: dict[str, Any], box: dict[str, Any], loc: str
) -> None:
    if "wait_word" in item:
        _require_wait_word(item.get("wait_word"), loc)
        box["wait_word"] = item["wait_word"]
    if "pace" in item and item.get("pace") is not None:
        box["pace"] = _require_pace(item.get("pace"), loc)
    if "emphasis" in item and item.get("emphasis") is not None:
        box["emphasis"] = _require_emphasis(item.get("emphasis"), loc)


def _require_wait_word(value: Any, loc: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{loc}.wait_word: must be a non-negative int")


def _require_pace(value: Any, loc: str) -> str:
    text = str(value).strip().lower()
    if text != "none":
        _fail(f"{loc}.pace: must be 'none' if set")
    return text


def _require_emphasis(value: Any, loc: str) -> str:
    text = str(value).strip().lower()
    if text not in ALLOWED_EMPHASIS:
        _fail(f"{loc}.emphasis: must be one of {sorted(ALLOWED_EMPHASIS)} if set")
    return text


def chart_value_violations(spec: dict[str, Any], corpus: str) -> list[str]:
    """Values whose digits are absent from ``corpus`` (the narration)."""
    issues: list[str] = []
    for loc, token in _chart_value_sites(spec):
        if _digits_documented(token, corpus):
            continue
        issues.append(
            f"{loc}: value {token} is not written as digits in the narration"
        )
    return issues


def _chart_value_sites(spec: dict[str, Any]) -> list[tuple[str, str]]:
    if not isinstance(spec, dict):
        return []
    pages = spec.get("pages")
    if not isinstance(pages, list):
        return []
    sites: list[tuple[str, str]] = []
    for index, page in enumerate(pages):
        sites.extend(_page_value_sites(page, index))
    return sites


def _page_value_sites(page: Any, index: int) -> list[tuple[str, str]]:
    if not isinstance(page, dict):
        return []
    chart = page.get("chart")
    if isinstance(chart, dict) and isinstance(chart.get("series"), list):
        return _series_value_sites(chart["series"], f"pages[{index}].chart.series")
    return _boxed_value_sites(page.get("rows"), f"pages[{index}]")


def _series_value_sites(series: list[Any], path: str) -> list[tuple[str, str]]:
    sites: list[tuple[str, str]] = []
    for index, item in enumerate(series):
        if not isinstance(item, dict):
            continue
        token = _optional_value_token(item.get("value"))
        if token:
            sites.append((f"{path}[{index}]", token))
    return sites


def _boxed_value_sites(rows: Any, path: str) -> list[tuple[str, str]]:
    if not isinstance(rows, list):
        return []
    sites: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        sites.extend(_row_value_sites(row, f"{path}.rows[{index}]"))
    return sites


def _row_value_sites(row: Any, path: str) -> list[tuple[str, str]]:
    if not isinstance(row, dict):
        return []
    boxes = row.get("boxes")
    if not isinstance(boxes, list):
        return []
    sites: list[tuple[str, str]] = []
    for index, box in enumerate(boxes):
        token = _box_value_token(box)
        if token:
            sites.append((f"{path}.boxes[{index}]", token))
    return sites


def _box_value_token(box: Any) -> str:
    if not isinstance(box, dict) or not box.get("chart_kind"):
        return ""
    return str(box.get("value_text") or "").strip()


def _optional_value_token(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if not math.isfinite(float(value)):
        return ""
    return _value_token(float(value))


def _digits_documented(token: str, corpus: str) -> bool:
    """True when ``token`` appears as its own number, not inside a longer one.

    A trailing sentence period matches (``12.``). A fractional continuation
    does not (``12`` is not documented by ``12.5``).
    """
    if not token:
        return False
    pattern = rf"(?<![\d.]){re.escape(token)}(?!\d|\.\d)"
    return re.search(pattern, corpus or "") is not None


def append_chart_page(
    lines: list[str],
    page_index: int,
    page: dict[str, Any],
    *,
    first_row_title_buff: float,
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> bool:
    """Emit chart mobjects. Return False so a diagram page uses the row layout."""
    rows = page.get("rows")
    if not isinstance(rows, list):
        return False
    kind = _rows_chart_kind(rows)
    if kind == "bar":
        _append_bars(lines, page_index, rows, first_row_title_buff)
        return True
    if kind == "line":
        _append_line_chart(
            lines,
            page_index,
            rows,
            first_row_title_buff,
            edges_with_target,
            page_edge_vars,
        )
        return True
    return False


def _rows_chart_kind(rows: list[Any]) -> str:
    for row in rows:
        if not isinstance(row, dict):
            continue
        boxes = row.get("boxes")
        if not isinstance(boxes, list) or not boxes:
            continue
        box = boxes[0]
        if isinstance(box, dict):
            return str(box.get("chart_kind") or "")
    return ""


def _append_bars(
    lines: list[str],
    page_index: int,
    rows: list[Any],
    first_row_title_buff: float,
) -> None:
    names: list[str] = []
    for index, row in enumerate(rows):
        var = f"_bx_{page_index}_{index}_0"
        _append_one_bar(lines, var, row["boxes"][0])
        names.append(var)
    joined = ", ".join(names)
    stack = f"_p{page_index}_chart"
    lines.append(
        f"        {stack} = VGroup({joined}).arrange(DOWN, buff=0.22, aligned_edge=LEFT)"
    )
    lines.append(f"        {stack}.next_to(title, DOWN, buff={first_row_title_buff})")


def _append_one_bar(lines: list[str], var: str, box: dict[str, Any]) -> None:
    label = str(box["label"])
    color = str(box["color"])
    width = _py_num(float(box["bar_width"]))
    height = _py_num(float(box["height"]))
    value = str(box["value_text"])
    lines.append(
        f"        {var}_slot = Rectangle(width=2.4, height={height}, stroke_width=0, fill_opacity=0)"
    )
    lines.append(
        f"        {var}_name = Text({label!r}, font_size=22, color=C_WHITE, font=MANIM_FONT)"
    )
    lines.append(f"        if {var}_name.width > 2.2:")
    lines.append(f"            {var}_name.scale_to_fit_width(2.2)")
    lines.append(f"        {var}_name.move_to({var}_slot).align_to({var}_slot, LEFT)")
    lines.append(
        f"        {var}_bar = Rectangle(width={width}, height={height}, stroke_width=0, "
        f"fill_color={color}, fill_opacity=0.92)"
    )
    lines.append(
        f"        {var}_val = Text({value!r}, font_size=20, color=C_WHITE, font=MANIM_FONT)"
    )
    lines.append(f"        {var}_bar.next_to({var}_slot, RIGHT, buff=0.16)")
    lines.append(f"        {var}_val.next_to({var}_bar, RIGHT, buff=0.14)")
    lines.append(
        f"        {var} = VGroup({var}_slot, {var}_name, {var}_bar, {var}_val)"
    )


def _py_num(value: float) -> str:
    return f"{round(value, 3):.3f}".rstrip("0").rstrip(".") or "0"


def _append_line_chart(
    lines: list[str],
    page_index: int,
    rows: list[Any],
    first_row_title_buff: float,
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> None:
    boxes = [row["boxes"][0] for row in rows]
    points = _plot_points(boxes)
    names: list[str] = []
    axis = _axis_span(points)
    for index, box in enumerate(boxes):
        var = f"_bx_{page_index}_{index}_0"
        x, y = points[index]
        _append_line_point(lines, var, box, x, y, axis if index == 0 else None)
        names.append(var)
    joined = ", ".join(names)
    stack = f"_p{page_index}_chart"
    lines.append(
        f"        {stack} = VGroup({joined}).next_to(title, DOWN, buff={first_row_title_buff})"
    )
    _append_line_segments(
        lines, page_index, boxes, edges_with_target, page_edge_vars
    )


def _axis_span(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(points) < 2:
        return None
    return points[0][0], points[-1][0]


def _plot_points(boxes: list[dict[str, Any]]) -> list[tuple[float, float]]:
    values = [float(box["value"]) for box in boxes]
    if not values:
        return []
    peak = max(values)
    count = len(values)
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = _PLOT_LEFT if count == 1 else _PLOT_LEFT + _PLOT_SPAN * index / (count - 1)
        y = _PLOT_HEIGHT * (value / peak)
        points.append((round(x, 3), round(y, 3)))
    return points


def _append_line_point(
    lines: list[str],
    var: str,
    box: dict[str, Any],
    x: float,
    y: float,
    axis: tuple[float, float] | None,
) -> None:
    color = str(box["color"])
    label = str(box["label"])
    value = str(box["value_text"])
    px, py = _py_num(x), _py_num(y)
    lines.append(
        f"        {var}_dot = Dot(point=[{px}, {py}, 0], color={color}, radius=0.08)"
    )
    lines.append(
        f"        {var}_name = Text({label!r}, font_size=20, color=C_WHITE, font=MANIM_FONT)"
    )
    lines.append(f"        if {var}_name.width > 1.6:")
    lines.append(f"            {var}_name.scale_to_fit_width(1.6)")
    lines.append(f"        {var}_name.next_to({var}_dot, DOWN, buff=0.12)")
    lines.append(
        f"        {var}_val = Text({value!r}, font_size=18, color=C_WHITE, font=MANIM_FONT)"
    )
    lines.append(f"        {var}_val.next_to({var}_dot, UP, buff=0.08)")
    if axis is None:
        lines.append(f"        {var} = VGroup({var}_dot, {var}_name, {var}_val)")
        return
    x0, x1 = _py_num(axis[0]), _py_num(axis[1])
    lines.append(
        f"        {var}_axis = Line([{x0}, 0, 0], [{x1}, 0, 0], color=C_WHITE, stroke_width=1.5)"
    )
    lines.append(
        f"        {var} = VGroup({var}_dot, {var}_name, {var}_val, {var}_axis)"
    )


def _append_line_segments(
    lines: list[str],
    page_index: int,
    boxes: list[dict[str, Any]],
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> None:
    for index in range(1, len(boxes)):
        _append_one_segment(
            lines, page_index, index, str(boxes[index]["color"]),
            edges_with_target, page_edge_vars,
        )


def _append_one_segment(
    lines: list[str],
    page_index: int,
    index: int,
    color: str,
    edges_with_target: dict[tuple[int, str], list[tuple[str, str]]],
    page_edge_vars: dict[int, list[str]],
) -> None:
    var = f"_bx_{page_index}_{index}_0"
    prev = f"_bx_{page_index}_{index - 1}_0"
    seg = f"_ln_{page_index}_{index}"
    lines.append(
        f"        {seg} = Line({prev}_dot.get_center(), {var}_dot.get_center(), "
        f"color={color}, stroke_width=3)"
    )
    page_edge_vars.setdefault(page_index, []).append(seg)
    edges_with_target.setdefault((page_index, var), []).append((seg, "draw"))
