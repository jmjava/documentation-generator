"""Remove regenerable pipeline outputs under a bundle (``Config.base_dir``).

Use :func:`clean_bundle_regenerable_outputs` from ``docgen clean-bundle`` or from
automation. Paths come from ``docgen.yaml`` ``dirs`` — the same layout ``docgen init`` creates.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config


def remove_narration_markdown_except_readme(narration_dir: Path) -> int:
    """Delete ``*.md`` under ``narration_dir`` except ``README.md`` (any case)."""
    if not narration_dir.is_dir():
        return 0
    n = 0
    for f in narration_dir.glob("*.md"):
        if f.name.lower() == "readme.md":
            continue
        f.unlink()
        n += 1
    return n


def wipe_animations_directory(animations_dir: Path) -> None:
    """Remove ``animations_dir`` and recreate an empty directory."""
    if animations_dir.exists():
        shutil.rmtree(animations_dir)
    animations_dir.mkdir(parents=True, exist_ok=True)


def wipe_terminal_directory(terminal_dir: Path) -> None:
    """Remove the terminal tree and recreate ``terminal/rendered`` (VHS / compose convention)."""
    if terminal_dir.exists():
        shutil.rmtree(terminal_dir)
    (terminal_dir / "rendered").mkdir(parents=True, exist_ok=True)


def wipe_per_function_outputs(per_function_dir: Path) -> int:
    """Remove LLM-generated ``*.docgen.yaml`` + ``*.html`` under ``per_function_dir``.

    These are Category C outputs of ``docgen per-function-generate``; the dir itself
    is preserved so a fresh regeneration can write into it. Returns count removed.
    Non-existent dir → 0.
    """
    if not per_function_dir.is_dir():
        return 0
    n = 0
    for pattern in ("*.docgen.yaml", "*.html"):
        for f in per_function_dir.glob(pattern):
            try:
                f.unlink()
                n += 1
            except OSError:
                continue
    return n


def clean_bundle_regenerable_outputs(
    cfg: "Config",
    *,
    keep_narration: bool = False,
) -> dict[str, Any]:
    """Delete generated outputs under ``cfg.base_dir`` only.

    **Preserves** (unless ``keep_narration``): ``docgen.yaml`` (unless removed separately),
    ``narration/README.md``, and segment ``narration/*.md`` when ``keep_narration`` is True.
    Clears ``recordings/per-function/*`` and ``per-function/*.{docgen.yaml,html}``
    (now Category C — emitted by ``docgen per-function-generate``).

    **Does not** touch ``repo_root`` fixtures.
    """
    base = cfg.base_dir.resolve()
    out: dict[str, Any] = {}

    if keep_narration:
        out["narration_md_removed"] = 0
    else:
        out["narration_md_removed"] = remove_narration_markdown_except_readme(cfg.narration_dir)
    wipe_animations_directory(cfg.animations_dir)
    out["animations_dir_reset"] = True

    mp3_n = 0
    if cfg.audio_dir.is_dir():
        for f in cfg.audio_dir.glob("*.mp3"):
            f.unlink()
            mp3_n += 1
    out["audio_mp3_removed"] = mp3_n

    wipe_terminal_directory(cfg.terminal_dir)
    out["terminal_dir_reset"] = True

    rec_mp4 = 0
    if cfg.recordings_dir.is_dir():
        for f in cfg.recordings_dir.glob("*.mp4"):
            f.unlink()
            rec_mp4 += 1
        per_fn = cfg.recordings_dir / "per-function"
        if per_fn.is_dir():
            shutil.rmtree(per_fn)
        per_fn.mkdir(parents=True, exist_ok=True)
    out["recordings_root_mp4_removed"] = rec_mp4

    out["per_function_outputs_removed"] = wipe_per_function_outputs(base / "per-function")

    state = base / ".docgen-state.json"
    if state.is_file():
        state.unlink()
        out["wizard_state_removed"] = True
    else:
        out["wizard_state_removed"] = False

    return out
