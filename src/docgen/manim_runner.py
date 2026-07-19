"""Manim scene renderer."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from docgen.binaries import resolve_binary

if TYPE_CHECKING:
    from docgen.config import Config


class ManimRunner:
    def __init__(self, config: Config) -> None:
        self.config = config

    def render(
        self,
        scenes: list[str] | None = None,
        *,
        scene: str | None = None,
    ) -> None:
        """Render Manim scenes.

        * ``scene=`` — single scene (CLI / wizard).
        * ``scenes=`` — explicit list (pipeline uses :meth:`Config.pipeline_manim_scene_names`).
        * Otherwise — ``config.manim`` ``scenes:`` list (legacy).

        Per-scene failures clear that scene's partial-movie cache and retry once
        with ``--flush_cache`` (handles corrupt partials left by interrupted runs).
        If any scene still fails after retry, raises :class:`RuntimeError`.
        """
        if scene is not None:
            to_render = [scene]
        elif scenes is not None:
            to_render = scenes
        else:
            to_render = self.config.manim_scenes
        if not to_render:
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
        failed: list[str] = []
        for s in to_render:
            if not self._render_one(manim_bin, scenes_file, s, quality_args):
                failed.append(s)
        if failed:
            raise RuntimeError(
                "Manim failed for scene(s): "
                + ", ".join(failed)
                + ". Partial caches were flushed and retried once; inspect "
                "animations/media or re-run `docgen manim --scene <Name>`."
            )

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

    def _clear_scene_partials(self, scene_name: str) -> None:
        """Remove partial movie files / output for one scene (corrupt-cache recovery)."""
        media = self.config.animations_dir / "media" / "videos" / "scenes"
        if not media.is_dir():
            return
        cleared = False
        for quality_dir in media.iterdir():
            if not quality_dir.is_dir():
                continue
            partials = quality_dir / "partial_movie_files" / scene_name
            if partials.is_dir():
                shutil.rmtree(partials, ignore_errors=True)
                cleared = True
            out = quality_dir / f"{scene_name}.mp4"
            if out.is_file():
                out.unlink(missing_ok=True)
                cleared = True
        if cleared:
            print(f"[manim] Cleared partial/cache output for {scene_name}")

    def _run_manim(
        self,
        manim_bin: str,
        scenes_file: Path,
        scene_name: str,
        quality_args: list[str],
        *,
        flush_cache: bool,
    ) -> None:
        cmd = [manim_bin, *quality_args]
        if flush_cache:
            cmd.append("--flush_cache")
        cmd.extend([str(scenes_file), scene_name])
        subprocess.run(
            cmd,
            check=True,
            cwd=str(self.config.animations_dir),
            timeout=300,
        )

    def _render_one(
        self,
        manim_bin: str,
        scenes_file: Path,
        scene_name: str,
        quality_args: list[str],
    ) -> bool:
        """Render one scene; on failure flush partials and retry once. Return success."""
        print(f"[manim] Rendering {scene_name}")
        try:
            self._run_manim(
                manim_bin, scenes_file, scene_name, quality_args, flush_cache=False
            )
            return True
        except FileNotFoundError:
            print(
                "[manim] manim executable not found. "
                "Install with `pip install manim` in this environment or set "
                "`manim.manim_path` in docgen.yaml."
            )
            return False
        except subprocess.TimeoutExpired:
            print(f"[manim] TIMEOUT {scene_name}")
            self._clear_scene_partials(scene_name)
            return False
        except subprocess.CalledProcessError as exc:
            print(f"[manim] FAILED {scene_name}: exit code {exc.returncode}")
            print(
                f"[manim] Retrying {scene_name} after clearing partials "
                "(--flush_cache)…"
            )
            self._clear_scene_partials(scene_name)
            try:
                self._run_manim(
                    manim_bin,
                    scenes_file,
                    scene_name,
                    quality_args,
                    flush_cache=True,
                )
                print(f"[manim] Retry OK {scene_name}")
                return True
            except subprocess.TimeoutExpired:
                print(f"[manim] TIMEOUT on retry {scene_name}")
                return False
            except subprocess.CalledProcessError as retry_exc:
                print(
                    f"[manim] FAILED retry {scene_name}: "
                    f"exit code {retry_exc.returncode}"
                )
                return False

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
        # Render-only flags: never pass -p (preview). Preview opens a GUI player
        # and fails with "Unable to create a GL context" on headless servers/CI;
        # compose reads the mp4 from animations/media/ directly.
        q = str(self.config.manim_quality).strip().lower()
        preset_map = {
            "480p15": (["-ql"], "480p15 (-ql)"),
            "720p30": (["-qm"], "720p30 (-qm)"),
            "1080p60": (["-qh"], "1080p60 (-qh)"),
            "2160p60": (["-qp"], "2160p60 (-qp)"),
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
            "falling back to 720p30 (-qm)."
        )
        return (["-qm"], "720p30 (-qm fallback)")
