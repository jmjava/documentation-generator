"""Declarative Manim scene specs (YAML) compiled to compliant Python.

LLMs are poor at reliable 2D layout in raw Manim code.  Instead they (or
humans) author a small **scene spec** — rows of labeled boxes, colors, and
optional ``wait_segment`` indices into ``timing.json``.  This module compiles
that spec into a ``class ...(_TimedScene)`` body that:

* Never leaves ``_box`` mobjects at the origin — every row is placed with
  ``VGroup(...).arrange(RIGHT, buff=...)`` and ``.next_to(anchor, DOWN, buff=...)``
  (single-box rows use ``.next_to`` on the box directly).
* Uses the shared ``_box`` helper (text centered in the rounded rect).

Typical workflow:

1. ``docgen scene-spec-generate --segment <id> --config docgen.yaml`` (YAML under ``animations/specs/``),
   or author ``animations/specs/<stem>.scene.yaml`` by hand.
2. ``docgen scene-compile path/to/spec.scene.yaml --config docgen.yaml`` (if not using ``--compile``).
3. ``docgen timestamps`` → ``docgen manim`` as usual.
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

SPEC_REQUIRED_TOP = ("segment_id", "class_name", "title", "rows")


class SceneSpecError(ValueError):
    """Invalid scene spec (schema or semantic)."""


def load_scene_spec(path: Path) -> dict[str, Any]:
    """Load and validate a ``*.scene.yaml`` file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SceneSpecError(f"{path}: root must be a mapping")
    validate_scene_spec(data, path_label=str(path))
    return data


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

    rows = data["rows"]
    if not isinstance(rows, list) or not rows:
        raise SceneSpecError(f"{path_label}: rows must be a non-empty list")

    layout = data.get("layout") or {}
    if layout and not isinstance(layout, dict):
        raise SceneSpecError(f"{path_label}: layout must be a mapping if present")

    for i, row in enumerate(rows):
        rp = f"{path_label}: rows[{i}]"
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
        for j, box in enumerate(boxes):
            bp = f"{rp}: boxes[{j}]"
            if not isinstance(box, dict):
                raise SceneSpecError(f"{bp}: box must be a mapping")
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

    lines: list[str] = [
        f"class {class_name}(_TimedScene):",
        "    def construct(self):",
        "        self.camera.background_color = C_BG",
        f"        timing = _load_timing({timing_key!r})",
        "",
        f"        title = Text({title_text!r}, font_size={title_fs}, color={title_color}).to_edge(UP)",
        "        self.timed_play(Write(title), run_time=2.0)",
    ]

    prev_anchor = "title"
    first_row = True

    for i, row in enumerate(spec["rows"]):
        ws = row.get("wait_segment")
        if ws is not None:
            lines.append(f"        if len(timing) > {int(ws)}:")
            lines.append(
                f"            self.wait_until(timing[{int(ws)}][\"start\"])"
            )
        gap = first_row_title_buff if first_row else row_gap
        first_row = False

        boxes_raw = row["boxes"]
        run_time = float(row["run_time"])

        box_names: list[str] = []
        for j, b in enumerate(boxes_raw):
            var = f"_bx_{i}_{j}"
            box_names.append(var)
            lab = str(b["label"])
            col = str(b["color"])
            w = float(b["width"])
            h = float(b["height"])
            fs = int(b["font_size"])
            lines.append(
                f"        {var} = _box({lab!r}, {col}, {w}, {h}, {fs})"
            )

        row_var = f"_row_{i}"
        if len(box_names) == 1:
            b0 = box_names[0]
            lines.append(
                f"        {b0}.next_to({prev_anchor}, DOWN, buff={gap})"
            )
            lines.append(
                f"        self.timed_play(FadeIn({b0}), run_time={run_time})"
            )
            prev_anchor = b0
        else:
            joined = ", ".join(box_names)
            lines.append(
                f"        {row_var} = VGroup({joined}).arrange(RIGHT, buff={column_gap}).next_to({prev_anchor}, DOWN, buff={gap})"
            )
            lines.append(
                f"        self.timed_play(FadeIn({row_var}), run_time={run_time})"
            )
            prev_anchor = row_var

    lines.extend(
        [
            "",
            "        # docgen: audio-length tail (waits through full TTS; run after `docgen timestamps`)",
            f"        _docgen_segs = _load_timing({timing_key!r})",
            "        if _docgen_segs:",
            "            self.wait_until(",
            '                max(float(s.get("end", 0.0)) for s in _docgen_segs)',
            "            )",
            "        self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)",
            "        self.timed_wait(0.5)",
        ]
    )

    return "\n".join(lines) + "\n"
