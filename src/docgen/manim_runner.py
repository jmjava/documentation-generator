"""Manim scene renderer."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config

_PRESET_FLAGS: dict[str, list[str]] = {
    "480p15": ["-ql"],
    "720p30": ["-qm"],
    "1080p60": ["-qh"],
    "2160p60": ["-qp"],
}

_CUSTOM_RE = re.compile(r"^(\d+)p(\d+)$")


class ManimRunner:
    def __init__(self, config: Config) -> None:
        self.config = config

    def render(self, scene: str | None = None) -> None:
        scenes = [scene] if scene else self.config.manim_scenes
        if not scenes:
            print("[manim] No scenes configured")
            return

        scenes_file = self.config.animations_dir / "scenes.py"
        if not scenes_file.exists():
            print(f"[manim] scenes.py not found at {scenes_file}")
            return

        manim_bin = self._find_manim()
        if not manim_bin:
            return

        quality_flags = self._quality_flags()
        for s in scenes:
            self._render_one(manim_bin, scenes_file, s, quality_flags)

    def _find_manim(self) -> str | None:
        """Locate the manim binary, checking the active venv first."""
        venv = Path(sys.prefix) / "bin" / "manim"
        if venv.is_file():
            return str(venv)

        found = shutil.which("manim")
        if found:
            return found

        print(
            "[manim] manim not found in PATH. "
            "Install with: pip install manim  (in this venv) "
            "or set PATH to include the directory containing manim."
        )
        return None

    def _render_one(
        self, manim_bin: str, scenes_file: Path, scene_name: str, quality_flags: list[str]
    ) -> None:
        quality_label = self.config.manim_quality
        print(f"[manim] Rendering {scene_name} at {quality_label}")
        cmd = [manim_bin, *quality_flags, str(scenes_file), scene_name]
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=str(self.config.animations_dir),
                timeout=self.config.ffmpeg_timeout,
            )
        except FileNotFoundError:
            print(
                "[manim] manim not found in PATH. "
                "Install with: pip install manim"
            )
        except subprocess.CalledProcessError as exc:
            print(f"[manim] FAILED {scene_name}: exit code {exc.returncode}")
        except subprocess.TimeoutExpired:
            print(f"[manim] TIMEOUT {scene_name} (limit {self.config.ffmpeg_timeout}s)")

    def _quality_flags(self) -> list[str]:
        """Return CLI flags for Manim based on the configured quality string.

        Recognised presets: 480p15, 720p30, 1080p60, 2160p60.
        Arbitrary ``<height>p<fps>`` strings (e.g. ``1080p30``) are parsed
        into explicit ``--resolution`` and ``--frame_rate`` flags.
        """
        q = self.config.manim_quality
        if q in _PRESET_FLAGS:
            return list(_PRESET_FLAGS[q])

        m = _CUSTOM_RE.match(q)
        if m:
            height = int(m.group(1))
            fps = int(m.group(2))
            width = _width_for_height(height)
            print(f"[manim] Using custom quality {width}x{height} @ {fps}fps")
            return ["--resolution", f"{width},{height}", "--frame_rate", str(fps)]

        valid = ", ".join(sorted(_PRESET_FLAGS.keys()))
        print(
            f"[manim] WARNING: quality '{q}' not recognised, "
            f"falling back to 720p30. Valid presets: {valid}  "
            f"(or use <height>p<fps> e.g. 1080p30)"
        )
        return ["-qm"]

    def quality_subdir(self) -> str:
        """Return the subdirectory name Manim uses for the configured quality."""
        q = self.config.manim_quality
        preset_dirs = {
            "480p15": "480p15",
            "720p30": "720p30",
            "1080p60": "1080p60",
            "2160p60": "2160p60",
        }
        if q in preset_dirs:
            return preset_dirs[q]
        m = _CUSTOM_RE.match(q)
        if m:
            return q
        return "720p30"


def _width_for_height(height: int) -> int:
    """Derive 16:9 width from height, rounding to even."""
    w = int(height * 16 / 9)
    return w + (w % 2)
