"""FFmpeg composition: combine audio + video into final segment recordings."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class Composer:
    def __init__(self, config: Config) -> None:
        self.config = config

    def compose_segments(self, segment_ids: list[str]) -> None:
        for seg_id in segment_ids:
            vmap = self.config.visual_map.get(seg_id, {})
            vtype = vmap.get("type", "vhs")
            if vtype == "manim":
                self.compose_simple(seg_id, self._manim_path(vmap))
            elif vtype == "vhs":
                self.compose_simple(seg_id, self._vhs_path(vmap))
            elif vtype == "mixed":
                sources = [self._resolve_source(s) for s in vmap.get("sources", [])]
                self.compose_mixed(seg_id, sources)
            elif vtype == "still":
                self.compose_still(seg_id, vmap.get("source", ""))
            else:
                print(f"[compose] Unknown type '{vtype}' for segment {seg_id}")

    def compose_simple(self, seg_id: str, video_path: Path) -> None:
        audio = self._find_audio(seg_id)
        if not audio:
            print(f"[compose] No audio for {seg_id}")
            return
        if not video_path.exists():
            print(f"[compose] Video not found: {video_path}")
            return

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"[compose] {seg_id}: {video_path.name} + {audio.name} -> {out.name}")

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(video_path),
            "-i", str(audio),
            "-c:v", "libx264", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        self._run_ffmpeg(cmd)

    def compose_mixed(self, seg_id: str, video_paths: list[Path]) -> None:
        audio = self._find_audio(seg_id)
        if not audio:
            return
        existing = [v for v in video_paths if v.exists()]
        if not existing:
            print(f"[compose] No video sources found for mixed segment {seg_id}")
            return

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Concat videos first, then add audio
        concat_list = out.parent / f".{seg_id}-concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{v}'" for v in existing), encoding="utf-8"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio),
            "-c:v", "libx264", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        self._run_ffmpeg(cmd)
        concat_list.unlink(missing_ok=True)

    def compose_still(self, seg_id: str, image_source: str) -> None:
        audio = self._find_audio(seg_id)
        if not audio:
            return
        img = self.config.base_dir / image_source
        if not img.exists():
            print(f"[compose] Still image not found: {img}")
            return

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(img),
            "-i", str(audio),
            "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        self._run_ffmpeg(cmd)

    def _find_audio(self, seg_id: str) -> Path | None:
        d = self.config.audio_dir
        if not d.exists():
            return None
        for mp3 in d.glob(f"*{seg_id}*.mp3"):
            return mp3
        return None

    def _manim_path(self, vmap: dict[str, Any]) -> Path:
        src = vmap.get("source", "")
        return self.config.animations_dir / "media" / "videos" / "scenes" / "720p30" / src

    def _vhs_path(self, vmap: dict[str, Any]) -> Path:
        src = vmap.get("source", "")
        return self.config.terminal_dir / "rendered" / src

    def _resolve_source(self, source: str) -> Path:
        # Try Manim first, then VHS
        manim_path = self.config.animations_dir / "media" / "videos" / "scenes" / "720p30" / source
        if manim_path.exists():
            return manim_path
        vhs_path = self.config.terminal_dir / "rendered" / source
        if vhs_path.exists():
            return vhs_path
        return self.config.base_dir / source

    def _output_path(self, seg_id: str) -> Path:
        # Match existing naming: find narration file stem or use seg_id
        for md in self.config.narration_dir.glob(f"*{seg_id}*.md"):
            return self.config.recordings_dir / f"{md.stem}.mp4"
        return self.config.recordings_dir / f"{seg_id}.mp4"

    @staticmethod
    def _run_ffmpeg(cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            print("[compose] ffmpeg not found in PATH")
        except subprocess.CalledProcessError as exc:
            print(f"[compose] ffmpeg failed: {exc.stderr[:300]}")
        except subprocess.TimeoutExpired:
            print("[compose] ffmpeg timed out")
