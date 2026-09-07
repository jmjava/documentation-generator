"""TTS narration generator (OpenAI gpt-4o-mini-tts or xAI / Grok ``/v1/tts``)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class TTSError(RuntimeError):
    """Raised when TTS cannot run (missing narration or pre-lint failure)."""


def _probe_duration(path: Path) -> float | None:
    """Return the duration of an audio file in seconds, or None on failure."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


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

        src = self.config.find_segment_asset(narration_dir, seg_id, ".md")
        if src is None:
            raise TTSError(
                f"No narration file found for segment {seg_id} "
                f"(expected {self.config.resolve_segment_name(seg_id)}.md under {narration_dir})"
            )
        raw = src.read_text(encoding="utf-8")
        plain = markdown_to_tts_plain(raw)

        lint_cfg = self.config.narration_lint_config
        if lint_cfg.get("block_tts_on_pre_lint", True):
            from docgen.narration_lint import lint_pre_tts

            deny = lint_cfg.get("pre_tts_deny_patterns")
            result = lint_pre_tts(raw, deny_patterns=deny)
            if not result.passed:
                details = "; ".join(result.issues[:8])
                raise TTSError(
                    f"pre-TTS lint failed for {seg_id} (block_tts_on_pre_lint): {details}"
                )

        if dry_run:
            print(f"[tts] {seg_id} — stripped text ({len(plain)} chars):")
            print(plain[:500])
            if len(plain) > 500:
                print(f"  ... ({len(plain) - 500} more chars)")
            return

        from docgen.ai_client import synthesize_speech

        audio_dir.mkdir(parents=True, exist_ok=True)

        stem = src.stem
        out_path = audio_dir / f"{stem}.mp3"

        old_duration = _probe_duration(out_path) if out_path.exists() else None

        print(f"[tts] Generating audio for {seg_id} ({len(plain)} chars) -> {out_path}")

        synthesize_speech(
            text=plain,
            model=self.config.tts_model,
            voice=self.config.tts_voice,
            instructions=self.config.tts_instructions,
            output_path=out_path,
            cfg=self.config,
        )
        print(f"[tts] Wrote {out_path}")

        new_duration = _probe_duration(out_path)
        if old_duration is not None and new_duration is not None and old_duration > 0:
            change_pct = ((new_duration - old_duration) / old_duration) * 100
            print(
                f"[tts] {seg_id}: {old_duration:.1f}s -> {new_duration:.1f}s "
                f"({change_pct:+.1f}%)"
            )
            if abs(change_pct) > 5:
                print(
                    f"[tts] WARNING: {seg_id} duration changed by {change_pct:+.1f}% — "
                    "scenes and timestamps need regeneration. "
                    "Run `docgen timestamps` and `docgen manim` to update."
                )
