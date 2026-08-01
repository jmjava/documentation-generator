"""Offline retime: recompile ``*.scene.yaml`` against current ``timing.json`` (no OpenAI)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config


def list_scene_spec_paths(cfg: "Config", *, segment_id: str | None = None) -> list[Path]:
    """Return ``animations/specs/*.scene.yaml`` paths (optionally one segment)."""
    specs_dir = cfg.animations_dir / "specs"
    if not specs_dir.is_dir():
        return []
    if segment_id is not None:
        sid = str(segment_id).strip()
        if sid.isdigit():
            sid = sid.zfill(2)
        stem = cfg.resolve_segment_name(sid)
        candidates = [
            specs_dir / f"{stem}.scene.yaml",
            specs_dir / f"{sid}.scene.yaml",
        ]
        return [p for p in candidates if p.is_file()]
    return sorted(specs_dir.glob("*.scene.yaml"))


def retime_compile_spec(
    cfg: "Config",
    spec_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Load one spec, re-derive ``wait_word`` from timing, compile into ``scenes.py``.

    Raises ``SceneGenerationError`` / ``SceneSpecError`` on schema or pacing failure.
    """
    from docgen.scene_spec import load_scene_spec
    from docgen.scene_spec_generate import (
        inject_class_block_into_scenes_py,
        linted_class_block_from_spec,
    )

    raw = load_scene_spec(spec_path)
    class_block, merged = linted_class_block_from_spec(cfg, dict(raw))
    sid = str(merged["segment_id"]).strip()
    class_name = str(merged["class_name"]).strip()
    if dry_run:
        return {
            "path": spec_path,
            "segment_id": sid,
            "class_name": class_name,
            "timing_key": merged.get("timing_key"),
            "class_block": class_block,
            "wrote": False,
        }
    scenes_path = inject_class_block_into_scenes_py(
        cfg, seg_id=sid, class_name=class_name, class_block=class_block
    )
    return {
        "path": spec_path,
        "segment_id": sid,
        "class_name": class_name,
        "timing_key": merged.get("timing_key"),
        "scenes_path": scenes_path,
        "wrote": True,
    }


def retime_compile_all(
    cfg: "Config",
    *,
    dry_run: bool = False,
    segment_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Retime-compile every (or selected) scene spec. Returns (results, error messages)."""
    from docgen.manim_scene_support import SceneGenerationError
    from docgen.scene_spec import SceneSpecError

    paths: list[Path] = []
    if segment_ids:
        for sid in segment_ids:
            paths.extend(list_scene_spec_paths(cfg, segment_id=str(sid)))
        # Dedupe while preserving order
        seen: set[Path] = set()
        uniq: list[Path] = []
        for p in paths:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                uniq.append(p)
        paths = uniq
    else:
        paths = list_scene_spec_paths(cfg)

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            results.append(retime_compile_spec(cfg, path, dry_run=dry_run))
        except (SceneGenerationError, SceneSpecError, OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    return results, errors
