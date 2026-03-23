"""Manim scene renderer."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


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

        quality_flag = self._quality_flag()
        for s in scenes:
            self._render_one(scenes_file, s, quality_flag)

    def _render_one(self, scenes_file, scene_name: str, quality_flag: str) -> None:
        print(f"[manim] Rendering {scene_name}")
        cmd = ["manim", quality_flag, str(scenes_file), scene_name]
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=str(self.config.animations_dir),
                timeout=300,
            )
        except FileNotFoundError:
            print("[manim] manim not found in PATH — install with: pip install manim")
        except subprocess.CalledProcessError as exc:
            print(f"[manim] FAILED {scene_name}: exit code {exc.returncode}")
        except subprocess.TimeoutExpired:
            print(f"[manim] TIMEOUT {scene_name}")

    def _quality_flag(self) -> str:
        q = self.config.manim_quality
        mapping = {"480p15": "-pql", "720p30": "-pqm", "1080p60": "-pqh"}
        return mapping.get(q, "-pqm")
