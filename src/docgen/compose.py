"""FFmpeg composition: combine audio + video into final segment recordings."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class ComposeError(RuntimeError):
    """Raised when composition would produce an unacceptable video."""


class Composer:
    def __init__(self, config: Config) -> None:
        self.config = config

    def compose_segments(self, segment_ids: list[str], *, strict: bool = True) -> int:
        composed = 0
        for seg_id in segment_ids:
            vmap = self.config.visual_map.get(seg_id, {})
            vtype = vmap.get("type", "vhs")
            seg_name = self.config.resolve_segment_name(seg_id)
            print(f"  [{seg_id}] {seg_name} ({vtype})")

            ok = False
            if vtype == "manim":
                ok = self._compose_simple(seg_id, self._manim_path(vmap), strict=strict)
            elif vtype == "vhs":
                ok = self._compose_simple(seg_id, self._vhs_path(vmap), strict=strict)
            elif vtype == "mixed":
                sources = [self._resolve_source(s) for s in vmap.get("sources", [])]
                ok = self._compose_mixed(seg_id, sources)
            elif vtype == "still":
                ok = self._compose_still(seg_id, vmap.get("source", ""))
            elif vtype == "image":
                ok = self._compose_image(seg_id, vmap.get("source", ""))
            else:
                print(f"    unknown type '{vtype}'")

            if ok:
                composed += 1

        print(f"\n=== Composed {composed} / {len(segment_ids)} segment videos ===")
        return composed

    def check_freeze_ratio(self, audio_dur: float, video_dur: float) -> float:
        """Return the freeze ratio that would result from composing these durations."""
        if audio_dur <= 0:
            return 0.0
        gap = max(0.0, audio_dur - video_dur)
        return gap / audio_dur

    def _compose_simple(self, seg_id: str, video_path: Path, *, strict: bool = True) -> bool:
        audio = self._find_audio(seg_id)
        if not audio:
            print(f"    SKIP: no audio for {seg_id}")
            return False
        if not video_path.exists():
            print(f"    SKIP: missing {video_path}")
            return False

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        audio_dur = self._probe_duration(audio)
        video_dur = self._probe_duration(video_path)
        if audio_dur is None or video_dur is None:
            print("    SKIP: cannot probe durations")
            return False

        freeze = self.check_freeze_ratio(audio_dur, video_dur)
        max_ratio = self.config.max_freeze_ratio
        if freeze > max_ratio:
            msg = (
                f"    FREEZE GUARD: {seg_id} visual is {video_dur:.1f}s but audio "
                f"is {audio_dur:.1f}s → {freeze:.0%} frozen "
                f"(max {max_ratio:.0%}). Re-render the visual source to be longer."
            )
            if strict:
                raise ComposeError(msg)
            print(f"    WARNING: {msg}")

        if video_dur < audio_dur:
            pad = audio_dur - video_dur
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path), "-i", str(audio),
                "-filter_complex",
                f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.3f}[v]",
                "-map", "[v]", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-t", f"{audio_dur:.3f}",
                "-movflags", "+faststart",
                str(out),
            ]
            self._run_ffmpeg(cmd)
            print(f"    ok video={video_dur:.1f}s + freeze {pad:.1f}s -> audio={audio_dur:.1f}s")
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path), "-i", str(audio),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-movflags", "+faststart",
                str(out),
            ]
            self._run_ffmpeg(cmd)
            print(f"    ok video={video_dur:.1f}s muxed to narration (~{audio_dur:.1f}s, -shortest)")

        return True

    def _compose_mixed(self, seg_id: str, video_paths: list[Path]) -> bool:
        audio = self._find_audio(seg_id)
        if not audio:
            print(f"    SKIP: no audio for {seg_id}")
            return False
        existing = [v for v in video_paths if v.exists()]
        if not existing:
            print(f"    SKIP: no video sources for mixed segment {seg_id}")
            return False

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        concat_list = out.parent / f".{seg_id}-concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{v}'" for v in existing), encoding="utf-8"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        self._run_ffmpeg(cmd)
        concat_list.unlink(missing_ok=True)

        ad = self._probe_duration(audio)
        print(f"    ok mixed concat + audio={ad:.1f}s" if ad else "    ok mixed concat")
        return True

    def _compose_still(self, seg_id: str, hex_color: str) -> bool:
        audio = self._find_audio(seg_id)
        if not audio:
            print(f"    SKIP: no audio for {seg_id}")
            return False

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=0x{hex_color}:s=1280x720:r=30",
            "-i", str(audio),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        self._run_ffmpeg(cmd)
        ad = self._probe_duration(audio)
        print(f"    ok still 1280x720 + audio={ad:.1f}s" if ad else "    ok still")
        return True

    def _compose_image(self, seg_id: str, relpath: str) -> bool:
        audio = self._find_audio(seg_id)
        if not audio:
            print(f"    SKIP: no audio for {seg_id}")
            return False

        img = self.config.base_dir / relpath
        if not img.exists():
            print(f"    SKIP: missing image {img}")
            return False

        out = self._output_path(seg_id)
        out.parent.mkdir(parents=True, exist_ok=True)

        audio_dur = self._probe_duration(audio)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", "30", "-i", str(img),
            "-i", str(audio),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                   "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{audio_dur:.3f}" if audio_dur else "",
            "-movflags", "+faststart",
            str(out),
        ]
        cmd = [c for c in cmd if c]
        self._run_ffmpeg(cmd)
        print(f"    ok image {img.name} + audio={audio_dur:.1f}s" if audio_dur else "    ok image")
        return True

    def _find_audio(self, seg_id: str) -> Path | None:
        d = self.config.audio_dir
        if not d.exists():
            return None
        seg_name = self.config.resolve_segment_name(seg_id)
        exact = d / f"{seg_name}.mp3"
        if exact.exists():
            return exact
        for mp3 in d.glob(f"{seg_id}-*.mp3"):
            return mp3
        for mp3 in d.glob(f"*{seg_id}*.mp3"):
            return mp3
        return None

    def _manim_path(self, vmap: dict[str, Any]) -> Path:
        src = vmap.get("source", "")
        base = self.config.animations_dir / "media" / "videos" / "scenes"
        return self._resolve_quality_path(base, src)

    def _vhs_path(self, vmap: dict[str, Any]) -> Path:
        src = vmap.get("source", "")
        rendered = self.config.terminal_dir / "rendered" / src
        if self.config.compose_warn_stale:
            self._check_stale_vhs(src, rendered)
        return rendered

    def _check_stale_vhs(self, source_name: str, rendered: Path) -> None:
        """Warn if a .tape file is newer than its rendered mp4."""
        if not rendered.exists():
            return
        stem = Path(source_name).stem
        terminal_dir = self.config.terminal_dir
        for tape in terminal_dir.glob(f"*{stem}*.tape"):
            if tape.stat().st_mtime > rendered.stat().st_mtime:
                print(
                    f"    WARNING: {tape.name} is newer than {rendered.name} — "
                    f"run 'docgen vhs' to re-render before composing."
                )
                break

    def _resolve_quality_path(self, base: Path, source: str) -> Path:
        """Find the rendered Manim file, trying the configured quality first,
        then falling back to any available quality directory."""
        from docgen.manim_runner import ManimRunner
        preferred = ManimRunner(self.config).quality_subdir()

        candidate = base / preferred / source
        if candidate.exists():
            return candidate

        for subdir in ("1080p60", "1080p30", "1440p60", "720p30", "480p15", "2160p60"):
            candidate = base / subdir / source
            if candidate.exists():
                if subdir != preferred:
                    print(
                        f"    NOTE: using {subdir}/{source} "
                        f"(configured quality {preferred} not found)"
                    )
                return candidate

        no_scenes = base.parent / preferred / source
        if no_scenes.exists():
            return no_scenes
        for subdir in ("1080p60", "1080p30", "1440p60", "720p30", "480p15", "2160p60"):
            no_scenes = base.parent / subdir / source
            if no_scenes.exists():
                return no_scenes

        return base / preferred / source

    def _resolve_source(self, source: str) -> Path:
        base = self.config.animations_dir / "media" / "videos" / "scenes"
        manim_path = self._resolve_quality_path(base, source)
        if manim_path.exists():
            return manim_path
        vhs_path = self.config.terminal_dir / "rendered" / source
        if vhs_path.exists():
            return vhs_path
        return self.config.base_dir / source

    def _output_path(self, seg_id: str) -> Path:
        seg_name = self.config.resolve_segment_name(seg_id)
        return self.config.recordings_dir / f"{seg_name}.mp4"

    @staticmethod
    def _probe_duration(path: Path) -> float | None:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=30,
            )
            return float(out.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        timeout = self.config.ffmpeg_timeout
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            print("    ERROR: ffmpeg not found in PATH")
        except subprocess.CalledProcessError as exc:
            print(f"    ERROR: ffmpeg failed: {exc.stderr[:300]}")
        except subprocess.TimeoutExpired:
            print(
                f"    ERROR: ffmpeg timed out after {timeout}s. "
                f"Increase compose.ffmpeg_timeout in docgen.yaml for long scenes."
            )
