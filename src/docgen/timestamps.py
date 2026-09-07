"""Timing extraction for audio-visual synchronization → ``animations/timing.json``.

Two engines produce the same Whisper-shaped timing blocks
(``{"text", "segments", "words"}``):

* **local** (default) — offline alignment of the known narration text against
  the mp3 using ffmpeg ``silencedetect`` + proportional interpolation
  (:mod:`docgen.align`). No API calls; requires ``narration/<stem>.md``.
* **whisper** — network transcription (legacy). OpenAI ``whisper-1``, or
  xAI ``/v1/stt`` when ``ai.provider`` is ``grok``. Requires an API key.

Select via ``timestamps.engine`` in docgen.yaml or ``docgen timestamps --engine``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config

ENGINES = ("local", "whisper")


class TimestampError(RuntimeError):
    """Raised when timestamps cannot be extracted for required segments."""


class TimestampExtractor:
    def __init__(self, config: Config) -> None:
        self.config = config

    # ── Whisper engine (network) ─────────────────────────────────────

    def extract(self, audio_path: str | Path) -> dict[str, Any]:
        """Transcribe audio and return word-level timestamps (OpenAI Whisper or xAI STT)."""
        from docgen.ai_client import transcribe_audio

        return transcribe_audio(audio_path, cfg=self.config)

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
        """Extract timestamps for ``segments.all`` and write timing.json.

        Walks configured segment ids via :meth:`Config.find_segment_asset` (no
        ``*.mp3`` glob). Missing audio for a listed segment is an error. With
        no ``segments.all`` entries, existing ``timing.json`` is left unchanged.
        """
        chosen = self.resolve_engine(engine)
        print(f"[timestamps] engine: {chosen}")
        if chosen == "whisper":
            from docgen.ai_client import AIError, resolve_ai_settings

            st = resolve_ai_settings(self.config)
            if not st.supports_stt:
                raise AIError(
                    "timestamps --engine whisper needs speech-to-text; "
                    f"provider {st.provider!r} has none. Use engine local "
                    f"(offline) or OpenAI/Grok. {st.auth_help()}"
                )

        seg_ids = [str(s) for s in self.config.segments_all]
        if not seg_ids:
            print("[timestamps] segments.all is empty; leaving timing.json unchanged")
            return

        missing: list[str] = []
        jobs: list[tuple[str, Path]] = []
        for sid in seg_ids:
            mp3 = self.config.find_segment_asset(self.config.audio_dir, sid, ".mp3")
            if mp3 is None:
                stem = self.config.resolve_segment_name(sid)
                missing.append(f"{sid} ({stem}.mp3)")
            else:
                jobs.append((sid, mp3))
        if missing:
            raise TimestampError(
                "[timestamps] missing audio for segment(s): "
                + ", ".join(missing)
                + ". Run `docgen tts` first."
            )

        timing: dict[str, Any] = {}
        for sid, mp3 in jobs:
            key = mp3.stem
            print(f"[timestamps] Extracting timestamps for {sid} ({key})")
            if chosen == "whisper":
                timing[key] = self.extract(mp3)
            else:
                timing[key] = self.extract_local(mp3)

        out = self.config.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(timing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[timestamps] Wrote {out}")

        from docgen.manim_scene_support import sync_audio_tail_waits_in_scenes

        for msg in sync_audio_tail_waits_in_scenes(self.config):
            print(f"[timestamps] scenes.py: {msg}")
