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


def _json_kind(value: Any) -> str:
    return "null" if value is None else type(value).__name__


def _json_number_kind(row: dict[str, Any], time_key: str) -> str | None:
    """Return a kind label when *time_key* is not a JSON number; ``None`` when ok.

    ``bool`` is a subclass of ``int``: ``start: true`` used to become ``1.0s``.
    """
    if time_key not in row:
        return "missing"
    value = row[time_key]
    if value is None:
        return "null"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _json_kind(value)
    return None


def _require_timing_object_list(
    path_name: str, stem: str, payload: dict[str, Any], key: str
) -> None:
    """Require ``words`` / ``segments`` (when present and not null) to be object arrays
    whose ``start`` / ``end`` are JSON numbers.
    """
    if key not in payload:
        return
    value = payload[key]
    if value is None:
        return
    if not isinstance(value, list):
        raise TimestampError(
            f"{path_name}[{stem!r}].{key} must be a JSON array, not {_json_kind(value)}"
        )
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise TimestampError(
                f"{path_name}[{stem!r}].{key}[{i}] must be a JSON object, "
                f"not {_json_kind(item)}"
            )
        for time_key in ("start", "end"):
            kind = _json_number_kind(item, time_key)
            if kind is not None:
                raise TimestampError(
                    f"{path_name}[{stem!r}].{key}[{i}].{time_key} must be a JSON "
                    f"number, not {kind}"
                )


def load_bundle_timing(config: "Config") -> dict[str, Any]:
    """Load ``animations/timing.json``.

    A missing file is ``{}``. Corrupt JSON, a non-object root, a non-object
    per-stem value, a present ``words`` / ``segments`` field that is not an
    array of objects, or a row whose ``start`` / ``end`` is not a JSON number
    raises :class:`TimestampError` so compile/validate cannot treat garbage as
    empty ``words`` or wait until ``0.0``.
    """
    path = config.animations_dir / "timing.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TimestampError(
            f"{path.name} is not valid JSON ({exc}) — fix or delete it before "
            "timestamps/compile"
        ) from exc
    except OSError as exc:
        raise TimestampError(f"could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TimestampError(
            f"{path.name} root must be a JSON object, not {_json_kind(data)}"
        )
    for stem, payload in data.items():
        if not isinstance(payload, dict):
            raise TimestampError(
                f"{path.name}[{stem!r}] must be a JSON object, not {_json_kind(payload)}"
            )
        _require_timing_object_list(path.name, str(stem), payload, "words")
        _require_timing_object_list(path.name, str(stem), payload, "segments")
    return data


class TimestampExtractor:
    def __init__(self, config: Config) -> None:
        self.config = config

    # ── Whisper engine (network) ─────────────────────────────────────

    def extract(self, audio_path: str | Path) -> dict[str, Any]:
        """Transcribe audio and return word-level timestamps (OpenAI Whisper or xAI STT)."""
        from docgen.ai_client import transcribe_audio

        stem = Path(audio_path).stem
        block = transcribe_audio(audio_path, cfg=self.config)
        self._require_word_timings(stem, block)
        return block

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
        if not text.strip():
            raise TimestampError(
                f"[timestamps] narration/{stem}.md has no spoken text after markdown "
                "stripping — add prose before timestamps (same contract as TTS)"
            )
        ts_cfg = self.config.timestamps_config
        block = align_narration_to_audio(
            text,
            Path(audio_path),
            noise_db=float(ts_cfg.get("silence_noise_db", -35.0)),
            min_silence_sec=float(ts_cfg.get("min_silence_sec", 0.3)),
        )
        self._require_word_timings(stem, block)
        return block

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

    @staticmethod
    def _require_word_timings(stem: str, block: dict[str, Any]) -> None:
        words = block.get("words") if isinstance(block, dict) else None
        if not isinstance(words, list) or not words:
            raise TimestampError(
                f"[timestamps] {stem}: no word-level timings — "
                "alignment produced an empty `words` list"
            )

    def extract_all(self, engine: str | None = None) -> None:
        """Extract timestamps for ``segments.all`` and write timing.json.

        Walks configured segment ids via :meth:`Config.find_segment_asset` (no
        ``*.mp3`` glob). Missing audio for a listed segment is an error. With
        no ``segments.all`` entries, existing ``timing.json`` is left unchanged.

        Successful runs **merge** stems into the existing file (same as the
        wizard per-segment timestamps step) so extra keys not in
        ``segments.all`` are not wiped. Corrupt JSON, a non-object root, a
        non-object stem, a non-array ``words`` / ``segments`` field, or a row
        whose ``start`` / ``end`` is not a JSON number raises
        :class:`TimestampError` and the file is not rewritten.
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

        timing = dict(load_bundle_timing(self.config))
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
