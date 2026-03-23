"""Two-stage narration linting: pre-TTS text scan and post-TTS transcript scan."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class LintResult:
    stage: str
    passed: bool
    issues: list[str] = field(default_factory=list)


def lint_pre_tts(text: str, deny_patterns: list[str] | None = None) -> LintResult:
    """Scan stripped narration text for leaked metadata before calling TTS."""
    patterns = deny_patterns or [
        "target duration",
        "intended length",
        "visual:",
        "edit for voice",
        r"approximately \d+ minutes",
    ]
    builtin = [
        (r"^#+ ", "Markdown heading"),
        (r"\*\*[^*]+\*\*", "Bold markdown syntax"),
        (r"`[^`]+`", "Backtick code syntax"),
        (r"\[[^\]]+\]\([^)]+\)", "Markdown link syntax"),
        (r"^---+$", "Horizontal rule"),
        (r"^\*{3,}$", "Horizontal rule"),
        (r"^## Script", "Section marker"),
        (r"^\*?\(.*\)\*?$", "Stage direction"),
    ]

    issues: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        for pat in patterns:
            if re.search(pat, stripped, re.IGNORECASE):
                issues.append(f"Line {i}: deny-pattern '{pat}' matched: {stripped[:80]}")
        for pat, label in builtin:
            if re.search(pat, stripped):
                issues.append(f"Line {i}: {label}: {stripped[:80]}")

    return LintResult(stage="pre-tts", passed=len(issues) == 0, issues=issues)


def lint_post_tts(transcript: str, deny_patterns: list[str] | None = None) -> LintResult:
    """Scan Whisper transcript of generated audio for spoken artifacts."""
    patterns = deny_patterns or [
        "target duration",
        "narration segment",
        "script section",
        "edit for voice",
        "intended length",
        "visual colon",
        "markdown",
        "heading",
        "backtick",
    ]

    issues: list[str] = []
    lower = transcript.lower()
    for pat in patterns:
        if re.search(pat, lower, re.IGNORECASE):
            # Find context
            idx = lower.find(pat.lower())
            start = max(0, idx - 30)
            end = min(len(transcript), idx + len(pat) + 30)
            context = transcript[start:end]
            issues.append(f"Spoken artifact '{pat}' detected: ...{context}...")

    return LintResult(stage="post-tts", passed=len(issues) == 0, issues=issues)


class NarrationLinter:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.lint_cfg = config.narration_lint_config

    def lint_text(self, text: str) -> LintResult:
        return lint_pre_tts(text, self.lint_cfg.get("pre_tts_deny_patterns"))

    def lint_audio(self, audio_path: str) -> LintResult:
        from docgen.timestamps import TimestampExtractor

        extractor = TimestampExtractor(self.config)
        data = extractor.extract(audio_path)
        return lint_post_tts(data["text"], self.lint_cfg.get("post_tts_deny_patterns"))
