"""Full-demo concatenation from config concat map."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class ConcatBuilder:
    def __init__(self, config: Config) -> None:
        self.config = config

    def build(self, name: str | None = None) -> None:
        concat_map = self.config.concat_map
        if not concat_map:
            print("[concat] No concat map in config")
            return

        targets = {name: concat_map[name]} if name and name in concat_map else concat_map
        for out_name, seg_ids in targets.items():
            self._build_one(out_name, seg_ids)

    def _build_one(self, out_name: str, seg_ids: list[str]) -> None:
        recordings_dir = self.config.recordings_dir
        if not recordings_dir.exists():
            print("[concat] Recordings dir not found")
            return

        files: list[Path] = []
        for seg_id in seg_ids:
            found = list(recordings_dir.glob(f"*{seg_id}*.mp4"))
            if found:
                files.append(found[0])
            else:
                print(f"[concat] Missing recording for segment {seg_id}")

        if not files:
            print(f"[concat] No files to concatenate for {out_name}")
            return

        out = recordings_dir / out_name
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
        except Exception as exc:
            print(f"[concat] Failed: {exc}")
        finally:
            concat_list.unlink(missing_ok=True)
