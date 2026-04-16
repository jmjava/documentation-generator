"""Whisper-based timestamp extraction for audio-visual synchronization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class TimestampExtractor:
    def __init__(self, config: Config) -> None:
        self.config = config

    def extract(self, audio_path: str | Path) -> dict[str, Any]:
        """Transcribe audio and return word-level timestamps."""
        from docgen.ai_provider import get_provider

        provider = get_provider(self.config)
        whisper_model = self.config.ai_config.get("whisper_model", "whisper-1")
        return provider.transcribe(
            audio_path=audio_path,
            model=whisper_model,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )

    def extract_all(self) -> None:
        """Extract timestamps for all segments and write timing.json."""
        audio_dir = self.config.audio_dir
        if not audio_dir.exists():
            print("[timestamps] No audio directory found")
            return

        timing: dict[str, Any] = {}
        for mp3 in sorted(audio_dir.glob("*.mp3")):
            seg_id = mp3.stem
            print(f"[timestamps] Extracting timestamps for {seg_id}")
            timing[seg_id] = self.extract(mp3)

        out = self.config.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(timing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[timestamps] Wrote {out}")
