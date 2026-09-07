"""Full-demo concatenation from config concat map."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class ConcatError(RuntimeError):
    """Raised when concat cannot build a complete output."""


class ConcatBuilder:
    def __init__(self, config: Config) -> None:
        self.config = config

    def build(self, name: str | None = None) -> None:
        concat_map = self.config.concat_map
        if not isinstance(concat_map, dict) or not concat_map:
            print("[concat] No concat map in config")
            return

        if name:
            if name not in concat_map:
                raise ConcatError(
                    f"[concat] unknown target {name!r}; "
                    f"known: {', '.join(sorted(concat_map))}"
                )
            targets = {name: concat_map[name]}
        else:
            targets = concat_map
        for out_name, seg_ids in targets.items():
            if not isinstance(seg_ids, list):
                raise ConcatError(
                    f"[concat] {out_name}: segment list must be a YAML list, "
                    f"not {type(seg_ids).__name__}"
                )
            ids: list[str] = []
            for i, item in enumerate(seg_ids):
                if not isinstance(item, str) or not item.strip():
                    raise ConcatError(
                        f"[concat] {out_name}[{i}] must be a quoted string segment id, "
                        f"not {type(item).__name__} ({item!r})"
                    )
                ids.append(item)
            self._build_one(out_name, ids)

    def _build_one(self, out_name: str, seg_ids: list[str]) -> None:
        recordings_dir = self.config.recordings_dir
        if not recordings_dir.exists():
            raise ConcatError(f"[concat] recordings dir not found: {recordings_dir}")

        files: list[Path] = []
        missing: list[str] = []
        for seg_id in seg_ids:
            found = self.config.find_segment_asset(recordings_dir, str(seg_id), ".mp4")
            if found:
                files.append(found)
            else:
                missing.append(str(seg_id))
        if missing:
            raise ConcatError(
                "[concat] missing recording(s) for "
                + ", ".join(missing)
                + f" (needed for {out_name})"
            )
        if len(files) != len(seg_ids):
            raise ConcatError(
                f"[concat] {out_name}: expected {len(seg_ids)} files, got {len(files)}"
            )

        fname = out_name if out_name.endswith(".mp4") else f"{out_name}.mp4"
        out = recordings_dir / fname
        concat_list = recordings_dir / f".concat-{out_name}.txt"
        concat_list.write_text(
            "\n".join(f"file '{f.name}'" for f in files), encoding="utf-8"
        )

        print(f"[concat] {out_name}: {len(files)} segments -> {out}")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                 "-c", "copy", str(out)],
                check=True, capture_output=True, text=True, timeout=300,
                cwd=str(recordings_dir),
            )
        except FileNotFoundError as exc:
            raise ConcatError("[concat] ffmpeg not found in PATH") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "")[:400]
            raise ConcatError(f"[concat] ffmpeg failed: {detail}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ConcatError("[concat] ffmpeg timed out") from exc
        finally:
            concat_list.unlink(missing_ok=True)
