"""Manim scene renderer."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from docgen.binaries import resolve_binary

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

        self._check_font()

        quality_args, quality_label = self._quality_args()
        manim_bin = self._resolve_manim_binary()
        if not manim_bin:
            return

        font = self.config.manim_font
        print(f"[manim] Rendering at {quality_label}, font={font}")
        for s in scenes:
            self._render_one(manim_bin, scenes_file, s, quality_args)

    def _check_font(self) -> None:
        """Verify the configured font is installed on the system."""
        font = self.config.manim_font
        try:
            result = subprocess.run(
                ["fc-list", font],
                capture_output=True, text=True, timeout=10,
            )
            if not result.stdout.strip():
                print(
                    f"[manim] WARNING: font '{font}' not found by fc-list. "
                    "Pango may substitute a different font. "
                    f"Install it (e.g. `apt install fonts-liberation`) or set "
                    f"`manim.font` in docgen.yaml to an available font."
                )
            else:
                print(f"[manim] Font '{font}' verified via fc-list")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    def _render_one(
        self,
        manim_bin: str,
        scenes_file: Path,
        scene_name: str,
        quality_args: list[str],
    ) -> None:
        print(f"[manim] Rendering {scene_name}")
        cmd = [manim_bin, *quality_args, str(scenes_file), scene_name]
        try:
            subprocess.run(
                cmd,
                check=True,
                cwd=str(self.config.animations_dir),
                timeout=300,
            )
        except FileNotFoundError:
            print(
                "[manim] manim executable not found. "
                "Install with `pip install manim` in this environment or set "
                "`manim.manim_path` in docgen.yaml."
            )
        except subprocess.CalledProcessError as exc:
            print(f"[manim] FAILED {scene_name}: exit code {exc.returncode}")
        except subprocess.TimeoutExpired:
            print(f"[manim] TIMEOUT {scene_name}")

    def _resolve_manim_binary(self) -> str | None:
        configured = self.config.manim_path
        if configured and not Path(configured).is_absolute():
            configured = str((self.config.base_dir / configured).resolve())

        resolution = resolve_binary("manim", configured_path=configured)
        if resolution.path:
            return resolution.path

        print("[manim] manim executable not found.")
        if resolution.tried:
            print("[manim] Tried:")
            for candidate in resolution.tried:
                print(f"  - {candidate}")
        print(
            "[manim] Fix: install with `pip install manim` in this env, "
            "or set `manim.manim_path` in docgen.yaml."
        )
        return None

    def _quality_args(self) -> tuple[list[str], str]:
        q = str(self.config.manim_quality).strip().lower()
        preset_map = {
            "480p15": (["-pql"], "480p15 (-pql)"),
            "720p30": (["-pqm"], "720p30 (-pqm)"),
            "1080p60": (["-pqh"], "1080p60 (-pqh)"),
            "2160p60": (["-pqp"], "2160p60 (-pqp)"),
        }
        if q in preset_map:
            return preset_map[q]

        match = re.match(r"^(\d{3,4})p(\d{2})$", q)
        if match:
            height = int(match.group(1))
            fps = int(match.group(2))
            width = (height * 16) // 9
            if width % 2:
                width += 1
            return (
                ["--resolution", f"{width},{height}", "--frame_rate", str(fps)],
                f"{height}p{fps} (--resolution {width}x{height}, --frame_rate {fps})",
            )

        print(
            f"[manim] WARNING: quality '{self.config.manim_quality}' not recognized; "
            "falling back to 720p30 (-pqm)."
        )
        return (["-pqm"], "720p30 (-pqm fallback)")
