"""Per-segment pipeline asset graph (freshness + rebuild-from-here).

Used by the wizard to show which redo steps are fresh/stale/missing and to
cascade ``run`` from a chosen step through validate. Aligns with CLI
``generate-all`` defaults: after timestamps prefer offline ``scene-retime``
(LLM ``scene-spec`` remains an explicit expensive step).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config

# Default cascade after timestamps (offline retime, not OpenAI scene-spec).
DEFAULT_CASCADE: tuple[str, ...] = (
    "tts",
    "timestamps",
    "scene-retime",
    "manim",
    "compose",
    "validate",
)

# LLM scene-spec replaces scene-retime when the maintainer opts into regen.
LLM_SCENE_CASCADE: tuple[str, ...] = (
    "tts",
    "timestamps",
    "scene-spec",
    "manim",
    "compose",
    "validate",
)

KNOWN_STEPS = frozenset(
    {
        "tts",
        "timestamps",
        "scene-retime",
        "scene-spec",
        "manim",
        "compose",
        "validate",
    }
)


@dataclass(frozen=True)
class StepStatus:
    step: str
    status: str  # fresh | stale | missing | n/a
    detail: str
    path: str | None = None
    mtime: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cascade_steps(start: str, *, llm_scene_spec: bool = False) -> list[str]:
    """Return ordered steps from ``start`` inclusive through validate.

    ``start="scene-spec"`` always continues with the LLM cascade tail
    (manim → compose → validate), even when the default chain uses retime.
    """
    start = str(start).strip()
    if start not in KNOWN_STEPS:
        raise ValueError(f"unknown pipeline step: {start!r}")

    if start == "scene-spec":
        order = list(LLM_SCENE_CASCADE)
    elif llm_scene_spec:
        order = list(LLM_SCENE_CASCADE)
    else:
        order = list(DEFAULT_CASCADE)

    if start not in order:
        # e.g. start=scene-retime while llm_scene_spec=True — use default chain.
        order = list(DEFAULT_CASCADE)
    idx = order.index(start)
    return order[idx:]


def _mtime(path: Path | None) -> float | None:
    if path is None or not path.is_file():
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _rel(cfg: "Config", path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(cfg.base_dir))
    except ValueError:
        return str(path)


def _find_asset(directory: Path, seg_name: str, seg_id: str, ext: str) -> Path | None:
    if not directory.exists():
        return None
    exact = directory / f"{seg_name}{ext}"
    if exact.exists():
        return exact
    exact_id = directory / f"{seg_id}{ext}"
    if exact_id.exists():
        return exact_id
    for f in directory.glob(f"{seg_id}-*{ext}"):
        return f
    for f in directory.glob(f"{seg_id}*{ext}"):
        return f
    return None


def _timing_entry_exists(cfg: "Config", seg_name: str, audio: Path | None) -> bool:
    timing_path = cfg.animations_dir / "timing.json"
    if not timing_path.is_file():
        return False
    try:
        data = json.loads(timing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    if seg_name in data:
        return True
    if audio is not None and audio.stem in data:
        return True
    return False


def _scene_spec_path(cfg: "Config", seg_id: str, seg_name: str) -> Path | None:
    from docgen.scene_retime import list_scene_spec_paths

    paths = list_scene_spec_paths(cfg, segment_id=seg_id)
    if paths:
        return paths[0]
    # Fall back to conventional stem even if missing (for path reporting).
    candidate = cfg.animations_dir / "specs" / f"{seg_name}.scene.yaml"
    return candidate if candidate.is_file() else None


def _manim_visual_path(cfg: "Config", seg_id: str) -> Path | None:
    """Best-effort Manim/composed visual input path for freshness."""
    vmap = cfg.visual_map.get(seg_id, {})
    if not isinstance(vmap, dict):
        return None
    src = str(vmap.get("source", "")).strip()
    if src:
        for candidate in (cfg.animations_dir / src, cfg.base_dir / src):
            if candidate.is_file():
                return candidate
    # Search common Manim media layout for the scene class name.
    scene = str(vmap.get("scene") or vmap.get("class") or "").strip()
    media = cfg.animations_dir / "media" / "videos" / "scenes"
    if scene and media.is_dir():
        matches = sorted(media.rglob(f"{scene}.mp4"))
        if matches:
            return matches[0]
    return None


def _status(
    *,
    step: str,
    output: Path | None,
    upstream_mtimes: list[float | None],
    cfg: "Config",
    missing_detail: str,
    fresh_detail: str,
) -> StepStatus:
    out_m = _mtime(output)
    if out_m is None:
        return StepStatus(step, "missing", missing_detail, path=_rel(cfg, output))
    ups = [m for m in upstream_mtimes if m is not None]
    if ups and out_m < max(ups) - 1.0:
        return StepStatus(
            step,
            "stale",
            "output older than an upstream input",
            path=_rel(cfg, output),
            mtime=out_m,
        )
    return StepStatus(
        step, "fresh", fresh_detail, path=_rel(cfg, output), mtime=out_m
    )


def segment_step_statuses(cfg: "Config", seg_id: str) -> list[StepStatus]:
    """Compute freshness for each wizard pipeline step for ``seg_id``."""
    sid = str(seg_id).strip()
    if sid.isdigit():
        sid = sid.zfill(2)
    seg_name = cfg.resolve_segment_name(sid)

    narration = _find_asset(cfg.narration_dir, seg_name, sid, ".md")
    audio = _find_asset(cfg.audio_dir, seg_name, sid, ".mp3")
    timing_path = cfg.animations_dir / "timing.json"
    timing_ok = _timing_entry_exists(cfg, seg_name, audio)
    spec = _scene_spec_path(cfg, sid, seg_name)
    visual = _manim_visual_path(cfg, sid)
    recording = _find_asset(cfg.recordings_dir, seg_name, sid, ".mp4")

    narr_m = _mtime(narration)
    audio_m = _mtime(audio)
    timing_m = _mtime(timing_path) if timing_ok else None
    spec_m = _mtime(spec)
    visual_m = _mtime(visual)
    rec_m = _mtime(recording)

    out: list[StepStatus] = []

    # TTS
    if narration is None:
        out.append(StepStatus("tts", "missing", "no narration.md yet"))
    else:
        out.append(
            _status(
                step="tts",
                output=audio,
                upstream_mtimes=[narr_m],
                cfg=cfg,
                missing_detail="no audio mp3 — run TTS",
                fresh_detail="audio newer than (or equal to) narration",
            )
        )

    # Timestamps
    if audio is None:
        out.append(StepStatus("timestamps", "missing", "no audio — run TTS first"))
    elif not timing_ok:
        out.append(
            StepStatus(
                "timestamps",
                "missing",
                "no timing.json entry — run timestamps",
                path=_rel(cfg, timing_path),
            )
        )
    else:
        out.append(
            _status(
                step="timestamps",
                output=timing_path,
                upstream_mtimes=[audio_m],
                cfg=cfg,
                missing_detail="no timing.json",
                fresh_detail="timing.json newer than (or equal to) audio",
            )
        )

    # Scene retime / scene-spec share the same output artifact (*.scene.yaml + scenes.py).
    # Freshness is relative to narration + timing.
    for step_name in ("scene-retime", "scene-spec"):
        if not timing_ok and audio is None:
            out.append(
                StepStatus(step_name, "missing", "need audio + timestamps first")
            )
        elif spec is None:
            out.append(
                StepStatus(
                    step_name,
                    "missing",
                    "no animations/specs/*.scene.yaml",
                )
            )
        else:
            out.append(
                _status(
                    step=step_name,
                    output=spec,
                    upstream_mtimes=[narr_m, timing_m],
                    cfg=cfg,
                    missing_detail="no scene spec",
                    fresh_detail="scene spec newer than narration/timing",
                )
            )

    # Manim
    vt = str(cfg.visual_map.get(sid, {}).get("type", "")).strip().lower()
    if vt and vt != "manim":
        out.append(StepStatus("manim", "n/a", f"visual type {vt!r} (not manim)"))
    else:
        out.append(
            _status(
                step="manim",
                output=visual,
                upstream_mtimes=[spec_m, timing_m],
                cfg=cfg,
                missing_detail="no Manim visual mp4 — run manim",
                fresh_detail="visual newer than scene spec/timing",
            )
        )

    # Compose
    out.append(
        _status(
            step="compose",
            output=recording,
            upstream_mtimes=[audio_m, visual_m],
            cfg=cfg,
            missing_detail="no recording — run compose",
            fresh_detail="recording newer than audio/visual",
        )
    )

    # Validate is advisory — always runnable
    out.append(
        StepStatus(
            "validate",
            "n/a",
            "run to check drift / timing_sync / story_end / av_sync",
            path=_rel(cfg, recording),
            mtime=rec_m,
        )
    )
    return out


def segment_asset_report(cfg: "Config", seg_id: str) -> dict[str, Any]:
    """JSON-serializable asset graph summary for the wizard."""
    statuses = segment_step_statuses(cfg, seg_id)
    stale_or_missing = [
        s.step for s in statuses if s.status in ("stale", "missing")
    ]
    return {
        "segment_id": str(seg_id).strip().zfill(2)
        if str(seg_id).strip().isdigit()
        else str(seg_id).strip(),
        "steps": [s.to_dict() for s in statuses],
        "default_cascade": list(DEFAULT_CASCADE),
        "stale_or_missing": stale_or_missing,
    }
