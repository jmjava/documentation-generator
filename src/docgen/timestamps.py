"""Timing extraction for audio-visual synchronization → ``animations/timing.json``.

Two engines produce the same Whisper-shaped timing blocks
(``{"text", "segments", "words"}``):

* **local** (default) — offline alignment of the known narration text against
  the mp3 using ffmpeg ``silencedetect`` + proportional interpolation
  (:mod:`docgen.align`). No API calls; requires ``narration/<stem>.md``.
* **whisper** — OpenAI ``whisper-1`` transcription (legacy; requires
  ``OPENAI_API_KEY`` and network).

Select via ``timestamps.engine`` in docgen.yaml or ``docgen timestamps --engine``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config

ENGINES = ("local", "whisper")


class TimestampExtractor:
    def __init__(self, config: Config) -> None:
        self.config = config

    # ── Whisper engine (network) ─────────────────────────────────────

    def extract(self, audio_path: str | Path) -> dict[str, Any]:
        """Transcribe audio via OpenAI whisper-1 and return word-level timestamps."""
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

    # ── Local engine (offline alignment) ─────────────────────────────

    def extract_local(self, audio_path: Path) -> dict[str, Any]:
        """Align the known narration text for this mp3's stem against the audio.

        No transcription: the exact TTS input text is recovered from
        ``narration/<stem>.md`` and timed via silence detection.
        """
        from docgen.align import align_narration_to_audio
        from docgen.tts import markdown_to_tts_plain

        stem = Path(audio_path).stem
        narration = self.config.narration_dir / f"{stem}.md"
        if not narration.is_file():
            raise RuntimeError(
                f"[timestamps] local engine needs narration/{stem}.md (the text that "
                f"produced audio/{stem}.mp3). Restore the narration file or run "
                "`docgen timestamps --engine whisper`."
            )
        text = markdown_to_tts_plain(narration.read_text(encoding="utf-8"))
        ts_cfg = self.config.timestamps_config
        return align_narration_to_audio(
            text,
            Path(audio_path),
            noise_db=float(ts_cfg.get("silence_noise_db", -35.0)),
            min_silence_sec=float(ts_cfg.get("min_silence_sec", 0.3)),
        )

    # ── Orchestration ────────────────────────────────────────────────

    def resolve_engine(self, engine: str | None = None) -> str:
        chosen = (engine or "").strip().lower() or str(
            self.config.timestamps_config.get("engine", "local")
        ).strip().lower()
        if chosen not in ENGINES:
            raise RuntimeError(
                f"[timestamps] unknown engine {chosen!r}; use one of {', '.join(ENGINES)}"
            )
        return chosen

    def extract_all(self, engine: str | None = None) -> None:
        """Extract timestamps for all segments and write timing.json."""
        audio_dir = self.config.audio_dir
        if not audio_dir.exists():
            print("[timestamps] No audio directory found")
            return

        chosen = self.resolve_engine(engine)
        print(f"[timestamps] engine: {chosen}")

        timing: dict[str, Any] = {}
        for mp3 in sorted(audio_dir.glob("*.mp3")):
            seg_id = mp3.stem
            print(f"[timestamps] Extracting timestamps for {seg_id}")
            if chosen == "whisper":
                timing[seg_id] = self.extract(mp3)
            else:
                timing[seg_id] = self.extract_local(mp3)

        out = self.config.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(timing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[timestamps] Wrote {out}")

        from docgen.manim_scene_support import sync_audio_tail_waits_in_scenes

        for msg in sync_audio_tail_waits_in_scenes(self.config):
            print(f"[timestamps] scenes.py: {msg}")
