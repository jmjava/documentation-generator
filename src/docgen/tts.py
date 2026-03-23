"""TTS narration generator using OpenAI gpt-4o-mini-tts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


def markdown_to_tts_plain(text: str) -> str:
    """Strip markdown formatting, metadata, and stage directions from narration text."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        # Skip headings
        if stripped.startswith("#"):
            continue
        # Skip metadata lines
        if re.match(r"^(target duration|intended length|visual:|edit for voice)", stripped, re.I):
            continue
        # Skip stage directions like *(pause)* or (* transition *)
        if re.match(r"^\*?\(.*\)\*?$", stripped):
            continue
        # Skip horizontal rules
        if re.match(r"^[-*_]{3,}$", stripped):
            continue
        # Strip bold/italic markers
        stripped = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", stripped)
        # Strip inline code
        stripped = re.sub(r"`([^`]+)`", r"\1", stripped)
        # Strip links: [text](url) -> text
        stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        lines.append(stripped)
    return "\n".join(lines).strip()


class TTSGenerator:
    def __init__(self, config: Config) -> None:
        self.config = config

    def generate(self, segment: str | None = None, dry_run: bool = False) -> None:
        segments = [segment] if segment else self.config.segments_all
        for seg_id in segments:
            self._generate_one(seg_id, dry_run)

    def _generate_one(self, seg_id: str, dry_run: bool) -> None:
        narration_dir = self.config.narration_dir
        audio_dir = self.config.audio_dir

        # Find narration file
        candidates = list(narration_dir.glob(f"*{seg_id}*.md")) if narration_dir.exists() else []
        if not candidates:
            print(f"[tts] No narration file found for segment {seg_id}, skipping")
            return
        src = candidates[0]
        raw = src.read_text(encoding="utf-8")
        plain = markdown_to_tts_plain(raw)

        if dry_run:
            print(f"[tts] {seg_id} — stripped text ({len(plain)} chars):")
            print(plain[:500])
            if len(plain) > 500:
                print(f"  ... ({len(plain) - 500} more chars)")
            return

        import openai

        audio_dir.mkdir(parents=True, exist_ok=True)
        out_path = audio_dir / f"{seg_id}.mp3"

        # Find the output name matching the narration filename stem
        stem = src.stem
        out_path = audio_dir / f"{stem}.mp3"

        print(f"[tts] Generating audio for {seg_id} ({len(plain)} chars) -> {out_path}")

        client = openai.OpenAI()
        response = client.audio.speech.create(
            model=self.config.tts_model,
            voice=self.config.tts_voice,
            input=plain,
            instructions=self.config.tts_instructions,
        )
        response.stream_to_file(str(out_path))
        print(f"[tts] Wrote {out_path}")
