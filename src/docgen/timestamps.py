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
        import openai

        client = openai.OpenAI()
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )

        return {
            "text": result.text,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in (result.segments or [])
            ],
            "words": [
                {"start": w.start, "end": w.end, "word": w.word}
                for w in (result.words or [])
            ],
        }

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
