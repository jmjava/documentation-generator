"""Pre-render checks so bad scene assets fail before Manim / compose.

Historical failure modes this module is meant to catch **offline**:

* **Stuck boards** — FadeIn run_times race ``_clock`` (issue #66), then the
  diagram dumps and freezes while narration continues. Also dwell that
  overshoots the next ``wait_word``, or a long subject-beat hold with no
  mid-hold pulse (one Indicate then a multi-second freeze).
* **Overlaps** — a page stack that exceeds the Manim frame budget (boxes
  clip or collide). ``layout_budget_violations`` already exists at generate
  time; validate re-runs it so a stale spec cannot sneak into a render.
* **Font consistency** — ``Text()`` without an explicit ``font=`` picks up
  whatever Pango default the machine has. Compiled scenes must use
  ``MANIM_FONT``.
* **Stale helpers / stale compile** — ``scenes.py`` still has center-to-center
  arrows or a ``_box`` that cannot take ``shape=``, or the generated class
  no longer matches ``compile_scene_class`` (missing Indicate, old FadeIn).
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config


def _hold_span(ev: Any) -> float:
    pulses = getattr(ev, "hold_pulses", ()) or ()
    if pulses:
        return sum(float(p.wait_before) + float(p.run_time) for p in pulses)
    return float(getattr(ev, "dwell_run_time", 0.0) or 0.0)


def motion_end_time(ev: Any) -> float:
    """Clock after reveal FadeIn plus every hold pulse."""
    return float(ev.effective_at) + float(ev.run_time) + _hold_span(ev)


def dwell_overshoot_violations(
    events: list[Any],
    *,
    slack: float = 0.05,
    audio_end: float | None = None,
) -> list[str]:
    """Fail when fade + hold pulses would push ``_clock`` past the next spoken start."""
    issues: list[str] = []
    for i, ev in enumerate(events):
        nxt_start = None
        for later in events[i + 1 :]:
            if getattr(later, "word_start", None) is not None:
                nxt_start = float(later.word_start)
                break
        if nxt_start is None and audio_end:
            nxt_start = float(audio_end)
        if nxt_start is None:
            continue
        end = motion_end_time(ev)
        if end > nxt_start + slack:
            issues.append(
                f"stuck: dwell/reveal overshoots next wait_word "
                f"(label={ev.label!r} ends at {end:.2f}s, next start {nxt_start:.2f}s)"
            )
    return issues


def hold_idle_violations(
    events: list[Any],
    *,
    audio_end: float = 0.0,
    slack: float = 0.15,
) -> list[str]:
    """Fail when a long hold has no mid-hold pulse and the board would freeze."""
    from docgen.manim_primitives import (
        DWELL_CLOCK_MARGIN,
        MAX_STATIC_HOLD,
        MIN_DWELL_RUN_TIME,
    )

    allowed = MAX_STATIC_HOLD + MIN_DWELL_RUN_TIME + DWELL_CLOCK_MARGIN + slack
    issues: list[str] = []
    for i, ev in enumerate(events):
        if str(getattr(ev, "emphasis", "none") or "none") == "none":
            continue
        nxt_start = None
        for later in events[i + 1 :]:
            if getattr(later, "word_start", None) is not None:
                nxt_start = float(later.word_start)
                break
        if nxt_start is None and audio_end > 0:
            nxt_start = float(audio_end)
        if nxt_start is None:
            continue
        idle = float(nxt_start) - motion_end_time(ev)
        if idle > allowed:
            issues.append(
                f"stuck: hold idle {idle:.2f}s after {ev.label!r} "
                f"(max {allowed:.2f}s) — mid-hold pulse missing"
            )
    return issues


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _first_arg_id(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Name):
        return call.args[0].id
    return None


def motion_plan_from_source(source: str) -> list[str]:
    """Ordered reveal / dwell / wait tokens from a compiled ``construct`` body."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "construct":
                    body = list(item.body)
                    break
    plan: list[str] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            if _call_name(stmt.value) == "_arrow" and stmt.value.args:
                first = stmt.value.args[0]
                if isinstance(first, ast.Call) and _call_name(first) == "get_center":
                    plan.append("arrow:center")
                elif isinstance(first, ast.Name):
                    plan.append("arrow:edge")
            continue
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        call = stmt.value
        attr = _call_name(call)
        if attr == "wait_until_word" and len(call.args) >= 2:
            idx = call.args[1]
            if isinstance(idx, ast.Constant):
                plan.append(f"wait_word:{idx.value}")
            continue
        if attr == "timed_wait" and call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Constant):
                plan.append(f"hold_wait:{arg.value}")
            continue
        if attr != "timed_play":
            continue
        for arg in call.args:
            if not isinstance(arg, ast.Call):
                continue
            name = _call_name(arg)
            target = _first_arg_id(arg)
            if name == "FadeIn":
                has_shift = any(k.arg == "shift" for k in arg.keywords)
                if target and str(target).startswith("_bx_"):
                    plan.append(f"reveal:{'slide' if has_shift else 'fade'}:{target}")
                elif target and str(target).startswith("_ar_"):
                    plan.append(f"edge:fade:{target}")
            elif name == "GrowFromCenter" and target:
                plan.append(f"reveal:grow:{target}")
            elif name == "Indicate" and target:
                plan.append(f"dwell:pulse:{target}")
            elif name == "Circumscribe" and target:
                plan.append(f"dwell:ring:{target}")
            elif name == "GrowArrow" and target:
                plan.append(f"edge:grow:{target}")
            elif name == "FadeOut":
                plan.append("page_fade")
    return plan


def extract_class_source(scenes_text: str, class_name: str) -> str | None:
    try:
        tree = ast.parse(scenes_text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return ast.get_source_segment(scenes_text, node)
    return None


def helper_api_violations(scenes_text: str) -> list[str]:
    """Stale ``_box`` / ``_arrow`` / ``_TimedScene`` that will mis-render new specs."""
    from docgen.manim_scene_support import helper_needs_refresh

    try:
        tree = ast.parse(scenes_text)
    except SyntaxError as exc:
        return [f"helpers: scenes.py did not parse ({exc.msg})"]
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
    if not defined.intersection({"_box", "_arrow", "_TimedScene"}):
        return []
    issues: list[str] = []
    if "MANIM_FONT" not in scenes_text:
        issues.append(
            "font: scenes.py is missing MANIM_FONT — run `docgen scene-compile` "
            "to refresh helpers (Pango default fonts drift across machines)"
        )
    for name in ("_box", "_arrow", "_TimedScene"):
        if name in defined and helper_needs_refresh(tree, name):
            issues.append(
                f"helpers: {name} is stale (missing shape / edge-to-edge / not_past) — "
                "run `docgen scene-compile` to refresh helper bodies"
            )
    return issues


def compiled_scene_sync_violations(
    spec: dict[str, Any],
    words: list[dict[str, Any]] | None,
    scenes_text: str,
) -> list[str]:
    """Fail when ``scenes.py`` does not match a fresh compile of the spec."""
    from docgen.scene_spec import SceneSpecError, compile_scene_class

    class_name = str(spec.get("class_name") or "").strip()
    if not class_name:
        return ["compile_sync: spec is missing class_name"]
    actual = extract_class_source(scenes_text, class_name)
    if actual is None:
        return [
            f"compile_sync: {class_name} is not in scenes.py — "
            "run `docgen scene-compile` before `docgen manim`"
        ]
    try:
        expected_src = compile_scene_class(spec, words=words or None)
    except SceneSpecError as exc:
        return [f"compile_sync: cannot compile spec ({exc})"]
    expected = motion_plan_from_source(expected_src)
    got = motion_plan_from_source(actual)
    if expected == got:
        return []
    return [
        "compile_sync: generated class is stale vs spec + timing.json "
        f"(expected {expected} got {got}) — run `docgen scene-compile --retime`"
    ]


def scene_asset_violations_for_segment(cfg: "Config", seg_id: str) -> list[str]:
    """All pre-render issues for one manim segment (empty if nothing to check)."""
    from docgen.scene_retime import list_scene_spec_paths
    from docgen.scene_spec import (
        SceneSpecError,
        layout_budget_violations,
        load_scene_spec,
        reveal_cadence_violations,
        simulate_reveal_timeline,
        validate_scene_spec,
    )

    issues: list[str] = []
    scenes_path = cfg.animations_dir / "scenes.py"
    scenes_text = ""
    if scenes_path.is_file():
        scenes_text = scenes_path.read_text(encoding="utf-8")
        issues.extend(helper_api_violations(scenes_text))

    paths = list_scene_spec_paths(cfg, segment_id=seg_id)
    if not paths:
        return issues

    block: dict[str, Any] = {}
    timing_path = cfg.animations_dir / "timing.json"
    stem = cfg.resolve_segment_name(seg_id)
    if timing_path.is_file():
        import json

        try:
            data = json.loads(timing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        raw_block = data.get(stem) if isinstance(data, dict) else None
        if isinstance(raw_block, dict):
            block = raw_block
    words = block.get("words") if isinstance(block.get("words"), list) else []

    audio_end = 0.0
    for w in words:
        if isinstance(w, dict):
            try:
                audio_end = max(audio_end, float(w.get("end", 0.0)))
            except (TypeError, ValueError):
                pass

    for path in paths:
        try:
            spec = load_scene_spec(path)
        except SceneSpecError as exc:
            issues.append(f"overlap: {path.name}: {exc}")
            continue
        try:
            validate_scene_spec(spec, path_label=path.name)
        except SceneSpecError as exc:
            issues.append(f"overlap: {exc}")
            continue
        for msg in layout_budget_violations(spec):
            issues.append(f"overlap: {path.name}: {msg}")
        if words:
            events = simulate_reveal_timeline(spec, words, clamp_run_times=True)
            issues.extend(
                f"stuck: {m}" for m in reveal_cadence_violations(events, audio_end=audio_end)
            )
            issues.extend(dwell_overshoot_violations(events, audio_end=audio_end or None))
            issues.extend(hold_idle_violations(events, audio_end=audio_end))
            merged_clock = dict(spec)
            if not merged_clock.get("timing_key"):
                merged_clock["timing_key"] = stem
            try:
                from docgen.scene_clock_harness import (
                    clock_contract_violations,
                    run_compiled_scene_clock,
                )
                from docgen.scene_spec import compile_scene_class

                compiled = compile_scene_class(merged_clock, words=words)
                trace = run_compiled_scene_clock(compiled, words)
                issues.extend(
                    f"clock: {m}"
                    for m in clock_contract_violations(trace, words, audio_end=audio_end)
                )
            except Exception as exc:  # noqa: BLE001 — fail closed before Manim
                issues.append(
                    f"clock: compiled construct failed to execute ({exc}) — "
                    "run `docgen scene-compile --retime`"
                )
        if scenes_text:
            merged = dict(spec)
            if not merged.get("timing_key"):
                merged["timing_key"] = stem
            issues.extend(
                compiled_scene_sync_violations(merged, words or None, scenes_text)
            )
    return issues


def bundle_scene_asset_violations(cfg: "Config") -> list[str]:
    """Preflight every manim segment. Used by ``generate-all`` before Manim."""
    issues: list[str] = []
    for seg_id in cfg.segments_all:
        vm = cfg.visual_map.get(seg_id)
        if not isinstance(vm, dict):
            continue
        vt = str(vm.get("type", "")).strip().lower()
        if vt and vt != "manim":
            continue
        if not vt and not (vm.get("scene") or vm.get("class")):
            continue
        for msg in scene_asset_violations_for_segment(cfg, str(seg_id)):
            issues.append(f"[{seg_id}] {msg}")
    return issues
