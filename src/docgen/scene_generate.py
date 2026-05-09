"""LLM-driven Manim scene authoring for ``docgen scene-generate``.

The **project owner** supplies hints + context paths in ``docgen.yaml`` under
``manim_scene_generation`` (see :func:`merged_scene_generation_settings`).
This module builds a structured prompt, calls OpenAI, validates the response is
valid Python with the expected single ``class <Name>(_TimedScene):`` definition,
and injects the class into ``animations/scenes.py`` between idempotent marker
comments so subsequent runs replace the block in place rather than appending.

Design constraints:

* Output is **code only** (no narration, no explanation, no fences).
* The generated class must extend ``_TimedScene`` (or, as a fallback, ``Scene``)
  and may only reference helpers/palette constants defined at the top of
  ``scenes.py`` (``_box``, ``_arrow``, ``_load_timing``, ``C_BG`` …).
* AST validation is mandatory; render-validation is out of scope (too slow).
* If ``scenes.py`` does not exist or is missing the helpers, we bootstrap it
  from a baked template before injecting — so this command also works on
  fresh-init projects (e.g. ``course-builder`` after ``docgen init``).

Failure modes:

* OpenAI auth/permission/connection errors propagate as ``RuntimeError`` with
  remediation hints (mirroring ``demo_function``'s fail-loud TTS contract).
* AST validation failures save the raw response under
  ``animations/.scene-generate-drafts/<seg>.draft.py`` and raise
  :class:`SceneGenerationError` so the user can inspect the broken output.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config

from docgen.validate import lint_manim_timing_stub_antipattern

_TITLE_DOWN_OVERLAP_RE = re.compile(r"\.next_to\(\s*title\s*,\s*DOWN\b")
_SHIFT_LEFT_RE = re.compile(r"\.shift\(\s*LEFT\s*\*")
_SHIFT_RIGHT_RE = re.compile(r"\.shift\(\s*RIGHT\s*\*")


def lint_manim_title_down_row_collision_risk(code: str) -> list[str]:
    """Flag a layout anti-pattern that stacks a wide box over flanking side boxes.

    When two mobjects are placed with ``.shift(LEFT * n)`` / ``.shift(RIGHT * n)``
    and another uses ``.next_to(title, DOWN, ...)`` only, their bounding boxes
    often collide on the same horizontal band. Scene-generate should use
    ``VGroup(...).arrange(RIGHT)`` rows chained with ``.next_to(row, DOWN)`` instead.
    """
    if (
        _SHIFT_LEFT_RE.search(code)
        and _SHIFT_RIGHT_RE.search(code)
        and _TITLE_DOWN_OVERLAP_RE.search(code)
    ):
        # Init-style scenes may use ReplacementTransform with a title-anchored box;
        # do not block those wholesale.
        if "ReplacementTransform" in code:
            return []
        return [
            "layout: pairing `.shift(LEFT * …)` + `.shift(RIGHT * …)` with "
            "`.next_to(title, DOWN, …)` usually overlaps a centered box onto the "
            "side boxes; build `VGroup(left, right).arrange(RIGHT, buff=…)`, "
            "`row.next_to(title, DOWN, buff=…)`, then chain further rows with "
            "`.next_to(row, DOWN, buff=…)` only."
        ]
    return []

DEFAULT_MODEL = "gpt-4o"
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_CONTEXT_BYTES = 80_000

DEFAULT_SYSTEM_PROMPT = """You author Manim Community Edition scene classes for docgen demo videos.

Output discipline:
- Output ONLY a single Python class definition. No imports, no module-level code, no markdown fences, no explanations.
- The class must extend `_TimedScene`. Do NOT redefine `_TimedScene`, `_box`, `_arrow`, `_load_timing`, or any palette constant - they are already in scope from scenes.py.
- Inside `construct(self)`, use ONLY these helpers and constants:
    helpers: `_box(label, color, w, h, fs)`, `_arrow(start, end, color)`, `_load_timing(segment_key)`
    palette: C_BG, C_ACCENT, C_GREEN, C_ORANGE, C_BLUE, C_RED, C_TEAL, C_PURPLE, C_WHITE
    timing helpers: `self.timed_play(*anims, run_time=...)`, `self.wait_until(t)`, `self.timed_wait(d)`, `self._clock`
    manim primitives: Text, RoundedRectangle, Rectangle, Line, Dot, Arrow, VGroup, FadeIn, FadeOut, Write, Create, Indicate, Transform, ReplacementTransform, GrowFromEdge, ORIGIN, UP, DOWN, LEFT, RIGHT, NORMAL, GREY_B, GREY_D
- Frame is 1280x720; coordinates x in [-7.11, 7.11], y in [-4, 4]. Keep all mobjects inside this box.
- Layout / overlap (diagram readability — `docgen validate` is strict on fonts, but overlaps ruin demos):
    - **No accidental collisions:** every `_box` must keep clear margin from every other `_box`. Prefer **explicit rows**: build a row with `VGroup(left, right).arrange(RIGHT, buff=0.8)` (tune `buff` 0.6–1.2), then place the next row with `.next_to(row, DOWN, buff=0.6)`.
    - **Forbidden pattern:** side-by-side boxes positioned with `.shift(LEFT * n)` / `.shift(RIGHT * n)` while a **wide** box is anchored with `.next_to(title, DOWN, ...)` only — the centered-under-title box will sit at the **same depth** as the row and **cover** the flanking boxes. Fix: first complete the top row as a `VGroup`, then chain downward with `DOWN` from that row (or move the flanking row `UP` and the centered stack strictly `DOWN` with enough `buff`).
    - Use `.next_to(..., buff=...)` on every placement; default Manim gaps are often too tight for rounded `_box` labels. When in doubt, **increase `buff`** or **narrow** `_box` width `w`.
    - Titles use `.to_edge(UP)`; the **first** row of content should be `.next_to(title, DOWN, buff=0.5)` (single anchor), then **only** chain `DOWN` from the previous row — do not mix free `shift(LEFT/RIGHT)` on the same Y band as a full-width centered element.
- Sync beats with `_load_timing("<narration_audio_stem>")` when you need audio-aligned waits: each item has `start` / `end` / `text` (seconds). If the list is non-empty, you may call `self.wait_until(float(segs[i]["start"]))` before a beat that should land on spoken word `i`. If the list is empty (`timing.json` not yet generated), the scene MUST still render using only explicit `run_time` arguments to `timed_play` and optional `timed_wait` — never invent placeholder functions named `seg_start` / `seg_end`, and never call `self._clock` like a function.
- Narration is usually much longer than a few bullet labels: **spread meaningfully distinct visuals across the entire Whisper timeline**, not just the first 10–20 seconds. When `_load_timing(...)` returns segments, aim for **at least one clear on-screen change (new label, Transform, arrow, or layout shift) near the start of most segments**, pacing with `wait_until` on segment `start` times. Avoid front-loading every `FadeIn` then sitting on a static frame while implied audio would still be describing new ideas — that is exactly what makes demos feel "incomplete" after compose.
- On-screen text should be **short phrases** cueing each idea; the voice may use full sentences — visuals reinforce, they need not mirror every word.
- The first action in `construct` MUST be `self.camera.background_color = C_BG`.
- The last action in `construct` MUST be a fade-out of all mobjects: `self.timed_play(*[FadeOut(m) for m in self.mobjects], run_time=1.0)` followed by `self.timed_wait(0.5)`.
- Do not call `self.play(...)` directly; always use `self.timed_play` so the elapsed-clock contract holds.
- Do not import anything; do not reference `numpy as np` directly (use `np.array(...)` only - `np` is already imported via `from manim import *`).

Manim scene lint rules (`docgen validate` will fail the build if violated):
- `Text(...)` font_size MUST be >= 14. There is no exception. Use color/position/spacing for hierarchy instead of small fonts.
- Do NOT pass `weight=BOLD` to `Text(...)`. The bundled font has no bold variant; Manim silently substitutes a different font and the visual breaks. Use a brighter color or larger font_size for emphasis instead.
- Do NOT use any of these unicode characters anywhere in the source file (string literals, comments, or otherwise): right-arrow U+2192, left-arrow U+2190, left-right arrow U+2194, single guillemets U+203A U+2039, not-equal U+2260, less-equal U+2264, greater-equal U+2265, em-dash U+2014, en-dash U+2013, smart quotes U+2018 U+2019 U+201C U+201D, bullet U+2022, ellipsis U+2026. Replace with ASCII: `->`, `<-`, `<->`, `>`, `<`, `!=`, `<=`, `>=`, `-`, `--`, `'`, `'`, `"`, `"`, `*`, `...`. This applies to the string passed to Text(...) AND to any inline comments in the generated code.
- Visual arrows on screen are drawn with `_arrow(start, end, color)` — never spelled out as text glyphs.
"""


# Stable marker contract used by `_inject_or_replace`. Must remain stable:
# changing these strings breaks idempotent regeneration in existing repos.
MARKER_BEGIN_FMT = "# ── BEGIN GENERATED SCENE: {seg_id} ({class_name}) ──"
MARKER_END_FMT = "# ── END GENERATED SCENE: {seg_id} ──"


# Bootstrap template written to ``scenes.py`` when the file is missing or
# lacks the helpers we depend on. Keep this in sync with the canonical helpers
# at the top of ``docs/demos/animations/scenes.py``.
BOOTSTRAP_HEADER = '''"""
Manim scenes for docgen demo videos.

Pacing is driven by timing.json (generated by ``docgen timestamps``).
Scene classes below this header are authored or maintained by
``docgen scene-generate`` between marker blocks; helpers and palette are
hand-maintained.

Frame: 14.22 wide x 8 tall.  Coordinates x in [-7.11, 7.11], y in [-4, 4].
"""

from __future__ import annotations

import json
from pathlib import Path

from manim import *  # noqa: F401,F403

# ── Palette ──────────────────────────────────────────────────────────
C_BG = "#1e1e2e"
C_ACCENT = "#667eea"
C_GREEN = "#42b883"
C_ORANGE = "#f9a825"
C_BLUE = "#2979ff"
C_RED = "#ff5252"
C_TEAL = "#26c6da"
C_PURPLE = "#ce93d8"
C_WHITE = "#cdd6f4"


def _load_timing(segment_key: str) -> list[dict]:
    """Return Whisper segments from timing.json for a given segment key."""
    timing_path = Path(__file__).parent / "timing.json"
    if not timing_path.exists():
        return []
    data = json.loads(timing_path.read_text())
    return data.get(segment_key, {}).get("segments", [])


def _box(label, color, w=2.2, h=0.75, fs=18):
    r = RoundedRectangle(
        corner_radius=0.15, width=w, height=h,
        stroke_color=color, fill_color=color, fill_opacity=0.12,
    )
    t = Text(label, font_size=fs, color=color)
    t.move_to(r.get_center())
    return VGroup(r, t)


def _arrow(start, end, color="#cdd6f4"):
    return Arrow(start, end, color=color, stroke_width=2, buff=0.15, max_tip_length_to_length_ratio=0.12)


class _TimedScene(Scene):
    """Base with a clock that tracks elapsed scene time."""

    def setup(self):
        self._clock = 0.0

    def timed_play(self, *animations, run_time=1.0, **kwargs):
        self.play(*animations, run_time=run_time, **kwargs)
        self._clock += run_time

    def wait_until(self, target: float):
        gap = target - self._clock
        if gap > 0.05:
            self.wait(gap)
            self._clock += gap

    def timed_wait(self, duration: float):
        if duration > 0.05:
            self.wait(duration)
            self._clock += duration
'''


REQUIRED_HELPERS = ("_TimedScene", "_box", "_arrow", "_load_timing")


class SceneGenerationError(RuntimeError):
    """Raised when the LLM output is unusable (no class, wrong name, parse fail)."""


@dataclass(frozen=True)
class SceneGenerationSettings:
    model: str
    temperature: float
    max_context_bytes: int
    system_prompt: str
    hints: list[str]
    context_paths: list[str]
    context_globs: list[str]
    class_name: str | None  # set when YAML provides ``segments.<id>.class_name``


def _as_str_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, str):
        return [x] if x.strip() else []
    if isinstance(x, list):
        return [str(i).strip() for i in x if str(i).strip()]
    return []


def merged_scene_generation_settings(cfg: "Config", seg_id: str) -> SceneGenerationSettings:
    """Merge ``manim_scene_generation`` defaults with optional per-segment overrides.

    Layout::

        manim_scene_generation:
          model: gpt-4o
          temperature: 0.4
          max_context_bytes: 80000
          system_prompt: <override>
          hints: [...]
          context:
            paths: [...]
            globs: [...]
          segments:
            "<id>":
              class_name: <ClassName>Scene
              hints: [...]
              context:
                paths: [...]
                globs: [...]

    All hints are project-owner authored; nothing here is round-tripped from a
    prior LLM response.
    """
    root = cfg.raw.get("manim_scene_generation")
    if not isinstance(root, dict):
        root = {}
    seg_block = root.get("segments")
    seg: dict[str, Any] = {}
    if isinstance(seg_block, dict):
        raw_seg = seg_block.get(seg_id)
        if isinstance(raw_seg, dict):
            seg = raw_seg

    ctx_root = root.get("context") if isinstance(root.get("context"), dict) else {}
    ctx_seg = seg.get("context") if isinstance(seg.get("context"), dict) else {}
    paths = _as_str_list(ctx_root.get("paths")) + _as_str_list(ctx_seg.get("paths"))
    globs = _as_str_list(ctx_root.get("globs")) + _as_str_list(ctx_seg.get("globs"))

    hints = _as_str_list(root.get("hints")) + _as_str_list(seg.get("hints"))

    model = str(root.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    temperature = float(root.get("temperature", DEFAULT_TEMPERATURE))
    max_bytes = int(root.get("max_context_bytes", DEFAULT_MAX_CONTEXT_BYTES))

    sys_override = str(root.get("system_prompt", "")).strip()
    seg_sys = str(seg.get("system_prompt", "")).strip()
    if seg_sys:
        system_prompt = seg_sys
    elif sys_override:
        system_prompt = sys_override
    else:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    cls_name = str(seg.get("class_name", "")).strip() or None

    return SceneGenerationSettings(
        model=model,
        temperature=temperature,
        max_context_bytes=max_bytes,
        system_prompt=system_prompt,
        hints=hints,
        context_paths=paths,
        context_globs=globs,
        class_name=cls_name,
    )


def derive_class_name(seg_id: str, seg_name: str, override: str | None) -> str:
    """Return ``<Override>`` if provided, else ``<CamelCase(seg_name)>Scene``."""
    if override and override.strip():
        return override.strip()
    base = seg_name or seg_id
    base = re.sub(r"^\d+[-_]?", "", base)  # strip leading "08-" etc.
    parts = re.split(r"[-_\s]+", base)
    camel = "".join(p[:1].upper() + p[1:].lower() for p in parts if p)
    if not camel:
        camel = f"Segment{seg_id}"
    return f"{camel}Scene"


# ── Context collection ─────────────────────────────────────────────────────


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
    settings: SceneGenerationSettings,
    *,
    extra_paths: list[str],
) -> list[tuple[str, str]]:
    """Return ``(label, text)`` pairs respecting the configured byte budget."""
    limit = settings.max_context_bytes
    repo_root = cfg.repo_root.resolve()
    paths: list[Path] = []
    for rel in settings.context_paths + list(extra_paths):
        ap = _resolve_repo_path(repo_root, rel)
        if ap:
            paths.append(ap)
    paths.extend(_collect_paths_from_globs(repo_root, settings.context_globs))
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
        except OSError:
            continue
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


def extract_reference_classes(scenes_py_text: str, *, max_bytes: int = 30_000) -> str:
    """Extract existing class definitions from ``scenes.py`` as few-shot examples.

    Strips the bootstrap header (palette + helpers) and returns just the
    ``class ...:`` blocks, capped to ``max_bytes`` characters total. Used to
    teach the model the project's idiomatic timing pattern without re-sending
    the helpers it must not redefine.
    """
    if not scenes_py_text.strip():
        return ""
    try:
        tree = ast.parse(scenes_py_text)
    except SyntaxError:
        return ""
    lines = scenes_py_text.splitlines(keepends=True)
    chunks: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            start = node.lineno - 1
            end = (node.end_lineno or node.lineno) if hasattr(node, "end_lineno") else node.lineno
            block = "".join(lines[start:end])
            chunks.append(block)
    out = "\n\n".join(chunks)
    if len(out) > max_bytes:
        out = out[:max_bytes] + "\n# … [reference scenes truncated for prompt budget] …\n"
    return out


# ── Prompt assembly ────────────────────────────────────────────────────────


def build_user_message(
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
    """Assemble the user-role message sent to the LLM (deterministic given inputs)."""
    parts: list[str] = []
    parts.append(
        f"Generate a Manim scene class named `{class_name}` for segment `{seg_id}` "
        f"(narration file: `{seg_name}.md`)."
    )
    parts.append("")
    parts.append("--- NARRATION (spoken text; visuals must reinforce it) ---")
    parts.append(narration_text.strip() or "(narration file is empty)")

    parts.append("")
    parts.append(
        f"--- TIMING (Whisper segments accessible as `_load_timing({seg_name!r})`) ---"
    )
    if whisper_segments:
        compact = [
            {"i": i, "start": float(s.get("start", 0.0)), "end": float(s.get("end", 0.0)),
             "text": str(s.get("text", "")).strip()}
            for i, s in enumerate(whisper_segments[:25])
        ]
        parts.append(json.dumps(compact, indent=2))
        parts.append(
            "# Staging: use the segment start times above with `self.wait_until(start)` "
            "and match each segment's `text` gist to a visual beat so the picture evolves "
            "through the whole clip, not only at the beginning."
        )
    else:
        parts.append(
            "[]\n# timing.json is not yet populated for this segment. The scene must "
            "still render correctly when `_load_timing(...)` returns []: use explicit "
            "`timed_play` / `timed_wait` run_times only. Never emit `seg_start` / `seg_end` "
            "placeholders and never call `self._clock` as if it were a function."
        )

    all_hints = list(hints) + list(extra_hints)
    if all_hints:
        parts.append("")
        parts.append("--- PROJECT-OWNER HINTS ---")
        for h in all_hints:
            if h.strip():
                parts.append(f"- {h.strip()}")

    if reference_scenes:
        parts.append("")
        parts.append("--- REFERENCE SCENES (style + timing pattern; do NOT redefine helpers) ---")
        parts.append(reference_scenes)

    if source_snippets:
        parts.append("")
        parts.append("--- CONTEXT FILES ---")
        for label, body in source_snippets:
            parts.append(f"FILE: {label}\n```\n{body}\n```")

    parts.append("")
    parts.append(
        f"Output the `{class_name}` class definition only. No imports. No prose. No fences."
    )
    return "\n".join(parts)


# ── LLM call ───────────────────────────────────────────────────────────────


def call_llm(*, system_prompt: str, user_message: str, model: str, temperature: float) -> str:
    """Call OpenAI chat completions; convert auth/network errors into actionable RuntimeErrors."""
    import openai

    client = openai.OpenAI()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=float(temperature),
        )
    except openai.AuthenticationError as exc:
        raise RuntimeError(
            f"OpenAI rejected OPENAI_API_KEY (authentication failed): {exc}. "
            "Set a valid key or pass --dry-run to inspect the prompt only."
        ) from exc
    except openai.PermissionDeniedError as exc:
        raise RuntimeError(
            f"OpenAI permission denied for model {model!r}: {exc}. "
            "Pick a model your account is allowed to use, or update YAML "
            "manim_scene_generation.model."
        ) from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"OpenAI connection error: {exc} — re-run when connectivity is restored."
        ) from exc
    return response.choices[0].message.content or ""


# ── Output validation ──────────────────────────────────────────────────────


_FENCE_RE = re.compile(r"^```(?:python)?\s*\n(?P<body>[\s\S]*?)\n```\s*$", re.MULTILINE)


def strip_response_fences(text: str) -> str:
    """Strip a single ``\u200b```python ... \u200b``` `` wrapper if the model added one despite instructions."""
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        return m.group("body").strip()
    return text


def lint_generated_block(
    code: str,
    *,
    min_font_size: int = 14,
    unsafe_unicode: list[str] | None = None,
) -> list[str]:
    """Run the same checks ``docgen validate`` applies to scenes.py, scoped to ``code``.

    Returns a list of human-readable issue strings; empty means clean. The
    rules are deliberately a subset of :func:`docgen.validate._lint_manim_text_usage`
    so that anything caught here would have failed downstream validation. Run
    BEFORE writing the class into ``scenes.py`` so the file is never left in a
    state where ``docgen validate`` would fail because of LLM output.
    """
    issues: list[str] = []
    if unsafe_unicode:
        for lineno, line_text in enumerate(code.splitlines(), start=1):
            for ch in unsafe_unicode:
                if ch in line_text:
                    issues.append(
                        f"line {lineno}: unsafe unicode character "
                        f"U+{ord(ch):04X} ({ch!r}) — use ASCII equivalent"
                    )

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return issues  # validate_class_definition will surface the parse error

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_text = (
            (isinstance(node.func, ast.Name) and node.func.id == "Text")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "Text")
        )
        if not is_text:
            continue

        for kw in node.keywords:
            if kw.arg == "weight" and isinstance(kw.value, ast.Name) and kw.value.id == "BOLD":
                issues.append(
                    f"line {node.lineno}: Text(..., weight=BOLD) — Pango font has no bold "
                    "variant; emphasize with color/font_size instead"
                )
            if kw.arg == "font_size" and isinstance(kw.value, ast.Constant):
                val = kw.value.value
                if isinstance(val, (int, float)) and int(val) < min_font_size:
                    issues.append(
                        f"line {node.lineno}: Text() font_size={int(val)} is below "
                        f"minimum {min_font_size}; small text is unreadable in video"
                    )
    issues.extend(lint_manim_timing_stub_antipattern(tree, "generated"))
    issues.extend(lint_manim_title_down_row_collision_risk(code))
    return issues


def validate_class_definition(code: str, expected_class: str) -> ast.ClassDef:
    """Parse ``code`` and assert it contains exactly one matching ``class`` definition.

    Returns the ``ast.ClassDef`` node so callers can introspect further.
    Raises :class:`SceneGenerationError` with an actionable message otherwise.
    """
    if not code.strip():
        raise SceneGenerationError("LLM returned empty output")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SceneGenerationError(
            f"LLM output failed to parse as Python: {exc.msg} at line {exc.lineno}"
        ) from exc

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    other = [n for n in tree.body if not isinstance(n, ast.ClassDef)]
    if not classes:
        raise SceneGenerationError("LLM output contained no class definition")
    if len(classes) > 1:
        names = ", ".join(c.name for c in classes)
        raise SceneGenerationError(
            f"LLM output contained multiple class definitions ({names}); only one expected"
        )
    if other:
        forbidden = ", ".join(type(n).__name__ for n in other)
        raise SceneGenerationError(
            f"LLM output contained module-level non-class statements: {forbidden}"
        )
    cls = classes[0]
    if cls.name != expected_class:
        raise SceneGenerationError(
            f"LLM output class name mismatch: expected {expected_class!r}, got {cls.name!r}"
        )
    base_names = {b.id for b in cls.bases if isinstance(b, ast.Name)}
    if not base_names & {"_TimedScene", "Scene"}:
        raise SceneGenerationError(
            f"class {cls.name} must extend `_TimedScene` or `Scene` "
            f"(got bases: {sorted(base_names)})"
        )
    return cls


# ── Marker injection ───────────────────────────────────────────────────────


def _markers(seg_id: str, class_name: str) -> tuple[str, str]:
    return (
        MARKER_BEGIN_FMT.format(seg_id=seg_id, class_name=class_name),
        MARKER_END_FMT.format(seg_id=seg_id),
    )


def inject_or_replace(scenes_py_text: str, seg_id: str, class_name: str, class_block: str) -> str:
    """Insert ``class_block`` between marker comments, replacing any prior occurrence.

    The replacement is keyed on the ``seg_id`` end marker so the user can rename
    the class in YAML and the next regeneration still finds + replaces the
    correct block.
    """
    begin, end = _markers(seg_id, class_name)
    wrapped = f"\n\n{begin}\n{class_block.rstrip()}\n{end}\n"

    # Match either `BEGIN GENERATED SCENE: <seg_id> (...)` line followed by
    # any body up to the matching `END GENERATED SCENE: <seg_id>` line.
    pattern = re.compile(
        rf"\n*# ── BEGIN GENERATED SCENE: {re.escape(seg_id)} \([^)]*\) ──"
        rf"[\s\S]*?# ── END GENERATED SCENE: {re.escape(seg_id)} ──\n*",
        re.MULTILINE,
    )
    if pattern.search(scenes_py_text):
        return pattern.sub(wrapped, scenes_py_text)
    if not scenes_py_text.endswith("\n"):
        scenes_py_text += "\n"
    return scenes_py_text + wrapped


_AUDIO_TAIL_COMMENT = "# docgen: audio-length tail (waits through full TTS; run after `docgen timestamps`)"


def append_audio_tail_to_class_body(class_body: str, timing_json_key: str) -> str:
    """Insert ``wait_until`` from last Whisper ``end`` before the final mass FadeOut.

    LLM-generated scenes typically total ~15–20s of ``timed_play`` while TTS runs
    70–120s. Without this tail, ``docgen compose`` freeze-pads the video for the
    gap and the result looks broken / ``incomplete``.  ``timing_json_key`` must
    match the stem in ``audio/<stem>.mp3`` and the top-level key in
    ``animations/timing.json`` (e.g. ``01-overview``).

    Idempotent: if :data:`_AUDIO_TAIL_COMMENT` is already present, returns
    ``class_body`` unchanged.
    """
    if _AUDIO_TAIL_COMMENT in class_body:
        return class_body
    fade_needle = "self.timed_play(*[FadeOut(m) for m in self.mobjects]"
    lines = class_body.splitlines(keepends=True)
    fade_idx: int | None = None
    for i, line in enumerate(lines):
        if fade_needle in line:
            fade_idx = i
            break
    if fade_idx is None:
        return class_body
    m = re.match(r"^(\s*)", lines[fade_idx])
    indent = m.group(1) if m else ""
    inner = f"{indent}    "
    deeper = f"{indent}        "
    tail = (
        f"{indent}{_AUDIO_TAIL_COMMENT}\n"
        f"{indent}_docgen_segs = _load_timing({timing_json_key!r})\n"
        f"{indent}if _docgen_segs:\n"
        f"{inner}self.wait_until(\n"
        f"{deeper}max(float(s.get(\"end\", 0.0)) for s in _docgen_segs)\n"
        f"{inner})\n"
    )
    return "".join(lines[:fade_idx] + [tail, lines[fade_idx]])


def sync_audio_tail_waits_in_scenes(cfg: "Config") -> list[str]:
    """Patch ``animations/scenes.py`` generated blocks: add audio-length tail waits.

    For each segment in ``segments.all`` whose ``visual_map`` type is ``manim``
    and whose narration audio has Whisper segments in ``timing.json``, inject
    :func:`append_audio_tail_to_class_body` into the marked block for that
    segment id.

    Returns human-readable changelog lines (empty if nothing to do).  Intended
    to run from :meth:`docgen.timestamps.TimestampExtractor.extract_all`
    immediately after ``timing.json`` is written.
    """
    scenes_path = cfg.animations_dir / "scenes.py"
    timing_path = cfg.animations_dir / "timing.json"
    if not scenes_path.is_file() or not timing_path.is_file():
        return []
    try:
        timing = json.loads(timing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    text = scenes_path.read_text(encoding="utf-8")
    changes: list[str] = []

    for seg_id in cfg.segments_all:
        sid = str(seg_id)
        vm = cfg.visual_map.get(sid)
        if not isinstance(vm, dict) or str(vm.get("type", "")).lower() != "manim":
            continue
        stem = cfg.resolve_segment_name(sid)
        if not timing.get(stem, {}).get("segments"):
            continue

        block_re = re.compile(
            rf"# ── BEGIN GENERATED SCENE: {re.escape(sid)} \([^)]+\) ──\n"
            rf"[\s\S]*?"
            rf"# ── END GENERATED SCENE: {re.escape(sid)} ──",
        )
        m = block_re.search(text)
        if not m:
            continue
        block = m.group(0)
        if _AUDIO_TAIL_COMMENT in block:
            continue
        new_block = append_audio_tail_to_class_body(block, stem)
        if new_block == block:
            continue
        text = text[: m.start()] + new_block + text[m.end() :]
        changes.append(f"patched audio-length tail for segment {sid} ({stem})")

    if changes:
        scenes_path.write_text(text, encoding="utf-8")
    return changes


def ensure_scenes_bootstrap(scenes_path: Path) -> None:
    """Write ``scenes.py`` with the bootstrap header if missing or lacking helpers.

    A "lacking helpers" file is one that does not define every name in
    :data:`REQUIRED_HELPERS` at module scope. In that case we refuse to clobber
    user content and raise :class:`SceneGenerationError` so the user can fix the
    file by hand. We only write a bootstrap when the file is **missing or
    empty**.
    """
    if not scenes_path.exists() or not scenes_path.read_text(encoding="utf-8").strip():
        scenes_path.parent.mkdir(parents=True, exist_ok=True)
        scenes_path.write_text(BOOTSTRAP_HEADER, encoding="utf-8")
        return

    text = scenes_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise SceneGenerationError(
            f"{scenes_path} did not parse as Python ({exc.msg} at line {exc.lineno}). "
            "Fix the file before re-running scene-generate."
        ) from exc

    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
    missing = [h for h in REQUIRED_HELPERS if h not in defined]
    if missing:
        raise SceneGenerationError(
            f"{scenes_path} is missing required helpers: {missing}. "
            "Either restore the helpers (palette + _box + _arrow + _load_timing + _TimedScene) "
            f"or delete {scenes_path.name} so scene-generate can write a fresh bootstrap."
        )


# ── End-to-end driver ──────────────────────────────────────────────────────


def _load_narration(cfg: "Config", seg_id: str, seg_name: str) -> str:
    """Read ``narration/<seg_name>.md``; raise if missing (per fail-loud contract)."""
    nar_path = cfg.narration_dir / f"{seg_name}.md"
    if not nar_path.exists():
        raise SceneGenerationError(
            f"narration file not found: {nar_path}. "
            f"Run `docgen narration-generate --segment {seg_id}` first or author the file by hand."
        )
    return nar_path.read_text(encoding="utf-8")


def _load_timing_segments(cfg: "Config", seg_name: str) -> list[dict]:
    timing_path = cfg.animations_dir / "timing.json"
    if not timing_path.exists():
        return []
    try:
        data = json.loads(timing_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(data.get(seg_name, {}).get("segments", []))


@dataclass
class SceneGenerationResult:
    seg_id: str
    seg_name: str
    class_name: str
    scenes_path: Path
    raw_response: str
    cleaned_code: str
    prompt: str
    written: bool


def generate_scene(
    cfg: "Config",
    seg_id: str,
    *,
    extra_paths: list[str],
    extra_hints: list[str],
    class_name_override: str | None = None,
    dry_run: bool = False,
    print_only: bool = False,
) -> SceneGenerationResult:
    """Drive the full prompt → call → validate → inject loop.

    ``dry_run`` returns the assembled prompt without calling OpenAI; the result's
    ``raw_response`` and ``cleaned_code`` will be empty. ``print_only`` calls the
    model and validates the response but does not write to disk.
    """
    settings = merged_scene_generation_settings(cfg, seg_id)
    seg_name = cfg.resolve_segment_name(seg_id)
    class_name = derive_class_name(
        seg_id, seg_name, class_name_override or settings.class_name
    )
    narration_text = _load_narration(cfg, seg_id, seg_name)
    whisper_segments = _load_timing_segments(cfg, seg_name)

    scenes_path = cfg.animations_dir / "scenes.py"
    if scenes_path.exists():
        existing = scenes_path.read_text(encoding="utf-8")
    else:
        existing = ""
    reference_scenes = extract_reference_classes(existing)

    snippets = collect_source_snippets(cfg, settings, extra_paths=extra_paths)

    user_message = build_user_message(
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
        return SceneGenerationResult(
            seg_id=seg_id,
            seg_name=seg_name,
            class_name=class_name,
            scenes_path=scenes_path,
            raw_response="",
            cleaned_code="",
            prompt=user_message,
            written=False,
        )

    raw = call_llm(
        system_prompt=settings.system_prompt,
        user_message=user_message,
        model=settings.model,
        temperature=settings.temperature,
    )
    cleaned = strip_response_fences(raw)

    try:
        validate_class_definition(cleaned, class_name)
    except SceneGenerationError:
        drafts_dir = cfg.animations_dir / ".scene-generate-drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft = drafts_dir / f"{seg_id}.draft.py"
        draft.write_text(raw, encoding="utf-8")
        raise

    lint_issues = lint_generated_block(
        cleaned,
        min_font_size=cfg.manim_min_font_size,
        unsafe_unicode=cfg.manim_unsafe_unicode,
    )
    if lint_issues:
        drafts_dir = cfg.animations_dir / ".scene-generate-drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft = drafts_dir / f"{seg_id}.draft.py"
        draft.write_text(cleaned, encoding="utf-8")
        joined = "\n  ".join(lint_issues[:15])
        raise SceneGenerationError(
            f"Generated class for segment {seg_id} would fail `docgen validate` "
            f"manim_scene_lint:\n  {joined}\n"
            f"Draft saved to {draft}. Tighten YAML hints or `--hint`, then re-run."
        )

    cleaned = append_audio_tail_to_class_body(cleaned, seg_name)
    lint2 = lint_generated_block(
        cleaned,
        min_font_size=cfg.manim_min_font_size,
        unsafe_unicode=cfg.manim_unsafe_unicode,
    )
    if lint2:
        drafts_dir = cfg.animations_dir / ".scene-generate-drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft = drafts_dir / f"{seg_id}.draft.py"
        draft.write_text(cleaned, encoding="utf-8")
        joined = "\n  ".join(lint2[:15])
        raise SceneGenerationError(
            f"After audio-tail injection, segment {seg_id} failed manim_scene_lint:\n  {joined}\n"
            f"Draft saved to {draft}."
        )

    if print_only:
        return SceneGenerationResult(
            seg_id=seg_id,
            seg_name=seg_name,
            class_name=class_name,
            scenes_path=scenes_path,
            raw_response=raw,
            cleaned_code=cleaned,
            prompt=user_message,
            written=False,
        )

    ensure_scenes_bootstrap(scenes_path)
    text = scenes_path.read_text(encoding="utf-8")
    new_text = inject_or_replace(text, seg_id, class_name, cleaned)
    scenes_path.write_text(new_text, encoding="utf-8")

    return SceneGenerationResult(
        seg_id=seg_id,
        seg_name=seg_name,
        class_name=class_name,
        scenes_path=scenes_path,
        raw_response=raw,
        cleaned_code=cleaned,
        prompt=user_message,
        written=True,
    )
