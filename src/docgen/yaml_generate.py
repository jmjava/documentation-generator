"""Hybrid ``docgen yaml-generate``: structural defaults from disk + OpenAI prose blocks.

This does **not** replace an entire ``docgen.yaml`` in one shot. It:

1. **Merges safe defaults** into an in-memory dict (wizard archive excludes, optional
   skeleton blocks for ``narration_from_source`` / ``manim_scene_generation``).
2. **Discovers** ``visual_map`` from the bundle tree (Manim ``*Scene`` classes from
   ``animations/scenes.py`` in file order—**only when those assets exist**). Segments
   stay **unmapped** until a scene class is available (no invented ``SceneNN``
   placeholders), unless ``discovery.auto_visual_map: false``.
3. **Syncs** ``manim.scenes`` and ``manim_scene_generation.segments`` from ``visual_map``.
4. **Reports gaps** between ``narration/*.md`` and ``segments.all`` (opt-in list).
5. **Declares segments** from maintainer ``hints/*.md`` files that include YAML front matter
   with ``docgen.segment: { create: true, id, stem }`` (see ``merge_hint_declared_segments``).
   Optional ``docgen.wiring`` in the same front matter merges ``visual_map``, ``narration_from_source.segments``,
   and ``manim_scene_generation.segments`` after disk discovery (see ``merge_hint_wiring``) — **avoid hand-editing**
   those keys for hint-driven segments; run ``yaml-generate`` after editing hints.
6. Optionally calls **OpenAI** to draft ``tts.instructions`` and ``wizard.system_prompt``.

Writing the file uses PyYAML: **YAML comments and key order in the original file are
not preserved.** Prefer version control for review; keep hand-maintained prose in Git
and re-run after changing project context.

See ``docs/yaml-generate`` in the repository for usage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from docgen.config import Config

ARCHIVE_EXCLUDE = "**/archive/**"

DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_SYSTEM_PROMPT = """You help maintain docgen.yaml for a demo video pipeline.

Return **only** a single JSON object, no markdown fences, no explanation. Keys:
- "tts_instructions": string, multi-sentence TTS voice directions (pronunciations, tone, banned phrases for this project).
- "wizard_system_prompt": string, 2-4 short paragraphs: wizard should author spoken narration scripts in plain English for this product; no markdown in output.

Both strings must be plain UTF-8 text suitable for YAML folded scalars (no raw newlines that break JSON — use \\n only inside JSON string values)."""


def narration_segment_pairs(narration_dir: Path) -> list[tuple[str, str]]:
    """Return sorted (seg_id, stem) from ``narration/<NN-name>.md`` (skip README)."""
    if not narration_dir.is_dir():
        return []
    pairs: list[tuple[str, str]] = []
    for f in sorted(narration_dir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        m = re.match(r"^(\d{2})[-_]", f.stem)
        if not m:
            continue
        pairs.append((m.group(1), f.stem))
    return pairs


def segments_in_config(raw: dict[str, Any]) -> set[str]:
    seg = raw.get("segments") or {}
    if not isinstance(seg, dict):
        return set()
    all_ids = seg.get("all") or seg.get("default") or []
    if not isinstance(all_ids, list):
        return set()
    return {str(x) for x in all_ids}


def narration_not_in_segments(raw: dict[str, Any], narration_dir: Path) -> list[tuple[str, str]]:
    """Narration stems whose numeric id is missing from ``segments.all``."""
    have = segments_in_config(raw)
    out: list[tuple[str, str]] = []
    for seg_id, stem in narration_segment_pairs(narration_dir):
        if seg_id not in have:
            out.append((seg_id, stem))
    return out


def merge_defaults(
    raw: dict[str, Any], cfg: "Config", *, merge_hint_segments: bool = True
) -> list[str]:
    """Mutate ``raw`` with idempotent defaults. Returns human-readable changelog lines."""
    changes: list[str] = []
    rr = cfg.repo_root.resolve()
    wiz = raw.setdefault("wizard", {})
    if not isinstance(wiz, dict):
        wiz = {}
        raw["wizard"] = wiz
    ex = wiz.setdefault("exclude_patterns", [])
    if not isinstance(ex, list):
        ex = []
        wiz["exclude_patterns"] = ex
    if ARCHIVE_EXCLUDE not in ex:
        ex.append(ARCHIVE_EXCLUDE)
        changes.append(f"wizard.exclude_patterns: added {ARCHIVE_EXCLUDE!r}")

    nf_existing = raw.get("narration_from_source")
    if nf_existing is None:
        ctx_paths: list[str] = []
        for name in ("README.md", "AGENTS.md"):
            p = rr / name
            if p.is_file():
                ctx_paths.append(name)
        raw["narration_from_source"] = {
            "model": "gpt-4o-mini",
            "temperature": 0.65,
            "max_context_bytes": 120_000,
            "hints": [],
            "context": {"paths": ctx_paths, "globs": []},
        }
        changes.append("narration_from_source: added skeleton (context.paths from README/AGENTS when present)")
    elif isinstance(nf_existing, dict) and not nf_existing.get("context"):
        ctx_paths = []
        for name in ("README.md", "AGENTS.md"):
            p = rr / name
            if p.is_file():
                ctx_paths.append(name)
        if ctx_paths:
            nf_existing["context"] = {"paths": ctx_paths, "globs": []}
            changes.append("narration_from_source.context: seeded from repo root files")

    mg = raw.get("manim_scene_generation")
    if mg is None:
        raw["manim_scene_generation"] = {
            "model": "gpt-4o",
            "temperature": 0.4,
            "max_context_bytes": 80_000,
            "hints": [
                "Match palette and _TimedScene timing patterns from existing scenes in animations/scenes.py.",
            ],
            "context": {"paths": [], "globs": []},
        }
        changes.append("manim_scene_generation: added minimal skeleton")

    if merge_hint_segments:
        changes.extend(merge_hint_declared_segments(raw, cfg))

    changes.extend(discover_visual_map(raw, cfg))
    changes.extend(merge_hint_wiring(raw, cfg))
    return sorted(set(changes))


_MANIM_CLASS_RE = re.compile(r"^class\s+([A-Za-z_][A-Za-z0-9_]*Scene)\s*\(", re.MULTILINE)
_HINT_FRONT_MATTER_RE = re.compile(r"^---\s*\r?\n(?P<body>.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)


def _segment_id_sort_key(sid: str) -> tuple[int, str]:
    s = str(sid).strip()
    if s.isdigit():
        return (int(s), "")
    m = re.match(r"^(\d+)", s)
    if m:
        return (int(m.group(1)), s)
    return (10_000, s)


def parse_hint_docgen_front_matter(md_path: Path) -> dict[str, Any] | None:
    """Return the ``docgen`` mapping from hint file YAML front matter, if present."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _HINT_FRONT_MATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group("body"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    doc = data.get("docgen")
    return doc if isinstance(doc, dict) else None


def parse_hint_segment_declaration(md_path: Path) -> tuple[str, str] | None:
    """If ``md_path`` has YAML front matter declaring ``docgen.segment`` with ``create: true``, return (id, stem)."""
    doc = parse_hint_docgen_front_matter(md_path)
    if not doc:
        return None
    seg = doc.get("segment")
    if not isinstance(seg, dict) or not seg.get("create"):
        return None
    sid = seg.get("id")
    stem = seg.get("stem")
    if sid is None or stem is None:
        return None
    sid_s = str(sid).strip()
    stem_s = str(stem).strip()
    if not sid_s or not stem_s:
        return None
    if sid_s.isdigit():
        sid_s = sid_s.zfill(2)
    if not re.fullmatch(r"\d{2}", sid_s):
        return None
    return sid_s, stem_s


def collect_hint_segment_declarations(hints_dir: Path) -> dict[str, str]:
    """First declaration per segment id wins (paths sorted). Values: segment id → narration stem."""
    if not hints_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(hints_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        decl = parse_hint_segment_declaration(path)
        if not decl:
            continue
        sid, stem = decl
        if sid not in out:
            out[sid] = stem
    return out


def _segment_lists_to_update(raw: dict[str, Any]) -> list[list[str]]:
    seg = raw.get("segments")
    if not isinstance(seg, dict):
        return []
    buckets: list[list[str]] = []
    seen: set[int] = set()
    for key in ("default", "all"):
        lst = seg.get(key)
        if not isinstance(lst, list):
            continue
        lid = id(lst)
        if lid in seen:
            continue
        seen.add(lid)
        buckets.append(lst)
    return buckets


def merge_hint_declared_segments(raw: dict[str, Any], cfg: "Config") -> list[str]:
    """Insert ids into ``segments`` lists and ``segment_names`` from ``hints/*.md`` front matter."""
    disc = raw.get("discovery")
    if isinstance(disc, dict) and disc.get("merge_hint_segments") is False:
        return []
    declared = collect_hint_segment_declarations(cfg.hints_dir)
    if not declared:
        return []

    lists = _segment_lists_to_update(raw)
    if not lists:
        seg_block = raw.setdefault("segments", {})
        if not isinstance(seg_block, dict):
            seg_block = {}
            raw["segments"] = seg_block
        shared: list[str] = []
        seg_block["default"] = shared
        seg_block["all"] = shared
        lists = _segment_lists_to_update(raw)

    changes: list[str] = []
    for lst in lists:
        before = list(lst)
        for sid in declared:
            if sid not in lst:
                lst.append(sid)
        lst.sort(key=_segment_id_sort_key)
        if lst != before:
            changes.append("segments: merged ids from hints/*.md (docgen.segment.create)")

    names = raw.setdefault("segment_names", {})
    if not isinstance(names, dict):
        names = {}
        raw["segment_names"] = names
    for sid, stem in sorted(declared.items(), key=lambda x: _segment_id_sort_key(x[0])):
        if names.get(sid) != stem:
            names[sid] = stem
            changes.append(f"segment_names[{sid!r}]: set from hints ({stem!r})")

    return sorted(set(changes))


def _deep_merge_yaml_mapping(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge_yaml_mapping(dst[k], v)
        else:
            dst[k] = v


def collect_hint_wirings_by_segment(hints_dir: Path) -> dict[str, dict[str, Any]]:
    """Segment id -> ``docgen.wiring`` dict. Later paths in sorted order win."""
    if not hints_dir.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(hints_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        doc = parse_hint_docgen_front_matter(path)
        if not doc:
            continue
        decl = parse_hint_segment_declaration(path)
        if not decl:
            continue
        sid, _stem = decl
        wiring = doc.get("wiring")
        if not isinstance(wiring, dict) or not wiring:
            continue
        out[sid] = wiring
    return out


def merge_hint_wiring(raw: dict[str, Any], cfg: "Config") -> list[str]:
    """Apply ``visual`` overrides from hints, re-sync Manim lists, then merge narration / manim_scene blocks."""
    disc = raw.get("discovery")
    hint_merge_off = isinstance(disc, dict) and disc.get("merge_hint_segments") is False
    wirings = {} if hint_merge_off else collect_hint_wirings_by_segment(cfg.hints_dir)
    changes: list[str] = []

    if not hint_merge_off:
        vm = raw.setdefault("visual_map", {})
        if not isinstance(vm, dict):
            vm = {}
            raw["visual_map"] = vm
        for sid, w in sorted(wirings.items(), key=lambda x: _segment_id_sort_key(x[0])):
            vis = w.get("visual")
            if isinstance(vis, dict) and vis:
                vm[str(sid)] = dict(vis)
                changes.append(f"visual_map[{sid!r}]: merged from hints/*.md (docgen.wiring)")

    changes.extend(_sync_manim_scenes_from_visual_map(raw))
    changes.extend(_sync_manim_segments_from_visual_map(raw))

    if hint_merge_off or not wirings:
        return sorted(set(changes))

    nfs = raw.setdefault("narration_from_source", {})
    if not isinstance(nfs, dict):
        nfs = {}
        raw["narration_from_source"] = nfs
    nf_segs = nfs.setdefault("segments", {})
    if not isinstance(nf_segs, dict):
        nf_segs = {}
        raw["narration_from_source"]["segments"] = nf_segs

    mg = raw.setdefault("manim_scene_generation", {})
    if not isinstance(mg, dict):
        mg = {}
        raw["manim_scene_generation"] = mg
    mg_segs = mg.setdefault("segments", {})
    if not isinstance(mg_segs, dict):
        mg_segs = {}
        raw["manim_scene_generation"]["segments"] = mg_segs

    for sid, w in sorted(wirings.items(), key=lambda x: _segment_id_sort_key(x[0])):
        nar = w.get("narration")
        if isinstance(nar, dict) and nar:
            cur = nf_segs.get(str(sid))
            if isinstance(cur, dict):
                _deep_merge_yaml_mapping(cur, dict(nar))
            else:
                nf_segs[str(sid)] = dict(nar)
            changes.append(f"narration_from_source.segments[{sid!r}]: merged from hints")
        ms = w.get("manim_scene")
        if isinstance(ms, dict) and ms:
            cur = mg_segs.get(str(sid))
            if isinstance(cur, dict):
                _deep_merge_yaml_mapping(cur, dict(ms))
            else:
                mg_segs[str(sid)] = dict(ms)
            changes.append(f"manim_scene_generation.segments[{sid!r}]: merged from hints")

    return sorted(set(changes))


def manim_scene_class_names_in_order(scenes_py: Path) -> list[str]:
    """Return ``*Scene`` class names in source order from ``animations/scenes.py``.

    Names starting with ``_`` (e.g. ``_TimedScene``) are helpers / bases for generated
    scenes and are **not** wired as pipeline segments — they must not consume a
    slot in ``visual_map`` discovery.
    """
    if not scenes_py.is_file():
        return []
    text = scenes_py.read_text(encoding="utf-8", errors="replace")
    return [n for n in _MANIM_CLASS_RE.findall(text) if not n.startswith("_")]


def discover_visual_map(raw: dict[str, Any], cfg: "Config") -> list[str]:
    """Rebuild ``visual_map`` from ``animations/scenes.py`` Manim classes (file order).

    A segment is only wired when a ``class …Scene`` remains for it; otherwise it is
    **left out** so greenfield repos are not given fake wiring.

    Set ``discovery: { auto_visual_map: false }`` to skip and keep existing ``visual_map``.
    """
    disc = raw.get("discovery")
    if isinstance(disc, dict) and disc.get("auto_visual_map") is False:
        return []

    seg_block = raw.get("segments") or {}
    all_ids = seg_block.get("all") or seg_block.get("default") or []
    if not isinstance(all_ids, list) or not all_ids:
        return []

    scenes_py = cfg.animations_dir / "scenes.py"
    manim_classes = manim_scene_class_names_in_order(scenes_py)

    new_vm: dict[str, Any] = {}
    for idx, seg_id in enumerate(all_ids):
        if idx >= len(manim_classes):
            break
        scene = manim_classes[idx]
        new_vm[str(seg_id)] = {"type": "manim", "scene": scene, "source": f"{scene}.mp4"}

    vm = raw.get("visual_map")
    if not isinstance(vm, dict):
        vm = {}
        raw["visual_map"] = vm
    if vm != new_vm:
        vm.clear()
        vm.update(new_vm)
        return ["visual_map: discovered from animations/scenes.py"]
    return []


def _sync_manim_scenes_from_visual_map(raw: dict[str, Any]) -> list[str]:
    """Set ``manim.scenes`` to Manim scene names in ``segments.all`` order (deduped)."""
    vm = raw.get("visual_map") or {}
    if not isinstance(vm, dict):
        return []
    seg_block = raw.get("segments") or {}
    all_ids = seg_block.get("all") or seg_block.get("default") or []
    if not isinstance(all_ids, list):
        all_ids = []
    scenes: list[str] = []
    seen: set[str] = set()
    for sid in all_ids:
        spec = vm.get(str(sid))
        if not isinstance(spec, dict) or spec.get("type") != "manim":
            continue
        sc = spec.get("scene")
        if not sc:
            continue
        s = str(sc)
        if s not in seen:
            seen.add(s)
            scenes.append(s)
    manim = raw.setdefault("manim", {})
    if not isinstance(manim, dict):
        manim = {}
        raw["manim"] = manim
    old = manim.get("scenes")
    manim["scenes"] = scenes
    if old != scenes:
        return ["manim.scenes: synced from visual_map (manim entries)"]
    return []


def _sync_manim_segments_from_visual_map(raw: dict[str, Any]) -> list[str]:
    """Keep ``manim_scene_generation.segments`` aligned with ``visual_map`` Manim entries.

    ``scene-spec-generate`` / ``scene-compile`` keys off this block; when maintainers add or retarget a Manim
    segment in ``visual_map``, ``yaml-generate --merge-defaults`` refreshes the map
    (same as consumers editing ``docgen.yaml`` and re-running the tool).
    """
    vm = raw.get("visual_map")
    if not isinstance(vm, dict):
        return []
    mg = raw.get("manim_scene_generation")
    if not isinstance(mg, dict):
        return []

    synced: dict[str, dict[str, str]] = {}
    for seg_id, spec in sorted(vm.items(), key=lambda x: str(x[0])):
        if not isinstance(spec, dict):
            continue
        if spec.get("type") != "manim":
            continue
        cn = spec.get("scene")
        if not cn:
            continue
        synced[str(seg_id)] = {"class_name": str(cn)}

    old = mg.get("segments")
    mg["segments"] = synced
    if old != synced:
        return ["manim_scene_generation.segments: synced from visual_map (manim entries)"]
    return []


def collect_context_snippets(cfg: "Config", max_bytes: int = 48_000) -> list[tuple[str, str]]:
    """(label, text) for LLM user message, capped."""
    rr = cfg.repo_root.resolve()
    candidates = [
        rr / "README.md",
        rr / "AGENTS.md",
        cfg.base_dir / "README.md",
        cfg.yaml_path.parent / "README.md",
    ]
    seen: set[Path] = set()
    snippets: list[tuple[str, str]] = []
    total = 0
    for p in candidates:
        rp = p.resolve()
        if rp in seen or not rp.is_file():
            continue
        seen.add(rp)
        try:
            rel = str(rp.relative_to(rr))
        except ValueError:
            rel = str(rp)
        text = rp.read_text(encoding="utf-8", errors="replace")
        if total + len(text) > max_bytes:
            text = text[: max(0, max_bytes - total)] + "\n… [truncated]\n"
        snippets.append((rel, text))
        total += len(text)
        if total >= max_bytes:
            break
    return snippets


def _llm_yaml_hints_json(
    *,
    project_label: str,
    snippets: list[tuple[str, str]],
    existing_tts: str,
    existing_wizard: str,
    model: str,
) -> dict[str, str]:
    import openai

    parts = [
        f"Project: {project_label}",
        "",
        "Current docgen.yaml excerpts (may be empty):",
        "--- tts.instructions (trimmed) ---",
        (existing_tts[:4000] + ("…" if len(existing_tts) > 4000 else "")),
        "--- wizard.system_prompt (trimmed) ---",
        (existing_wizard[:4000] + ("…" if len(existing_wizard) > 4000 else "")),
        "",
        "--- Repository context ---",
    ]
    for label, body in snippets:
        parts.append(f"FILE: {label}\n```\n{body}\n```")
    user = "\n".join(parts)

    client = openai.OpenAI()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.35,
        )
    except openai.AuthenticationError as exc:
        raise RuntimeError(
            f"OpenAI rejected OPENAI_API_KEY: {exc}. Set a valid key or omit --llm."
        ) from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(f"OpenAI connection error: {exc}") from exc
    text = (resp.choices[0].message.content or "").strip()
    # tolerate markdown code fence
    m = re.match(r"^```(?:json)?\s*\n(?P<body>[\s\S]*?)\n```\s*$", text)
    if m:
        text = m.group("body").strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    ti = data.get("tts_instructions")
    ws = data.get("wizard_system_prompt")
    if not isinstance(ti, str) or not isinstance(ws, str):
        raise ValueError('LLM JSON must have string "tts_instructions" and "wizard_system_prompt"')
    return {"tts_instructions": ti.strip(), "wizard_system_prompt": ws.strip()}


def generate_llm_hints(cfg: "Config", *, model: str | None = None) -> dict[str, str]:
    """Call OpenAI; return ``tts_instructions`` and ``wizard_system_prompt``."""
    raw = cfg.raw
    tts = raw.get("tts") if isinstance(raw.get("tts"), dict) else {}
    wiz = raw.get("wizard") if isinstance(raw.get("wizard"), dict) else {}
    existing_tts = str(tts.get("instructions") or "")
    existing_wizard = str(wiz.get("system_prompt") or "")
    snippets = collect_context_snippets(cfg)
    if not snippets:
        raise ValueError(
            "No context files found (README.md / AGENTS.md). Add them at repo root or pass richer yaml later."
        )
    label = cfg.repo_root.name
    return _llm_yaml_hints_json(
        project_label=label,
        snippets=snippets,
        existing_tts=existing_tts,
        existing_wizard=existing_wizard,
        model=model or DEFAULT_LLM_MODEL,
    )


def apply_llm_hints(raw: dict[str, Any], hints: dict[str, str]) -> None:
    """Merge LLM strings into ``tts`` and ``wizard`` blocks."""
    tts = raw.setdefault("tts", {})
    if not isinstance(tts, dict):
        tts = {}
        raw["tts"] = tts
    tts["instructions"] = hints["tts_instructions"]
    wiz = raw.setdefault("wizard", {})
    if not isinstance(wiz, dict):
        wiz = {}
        raw["wizard"] = wiz
    wiz["system_prompt"] = hints["wizard_system_prompt"]


def write_docgen_yaml(path: Path, raw: dict[str, Any], *, header: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(
        raw,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )
    text = (header or "") + dumped
    path.write_text(text, encoding="utf-8")


def default_header(path: Path) -> str:
    return (
        f"# docgen.yaml — updated by docgen yaml-generate\n"
        f"# Source: {path.resolve()}\n"
        f"# Note: PyYAML rewrite drops comments; review diff in Git.\n\n"
    )
