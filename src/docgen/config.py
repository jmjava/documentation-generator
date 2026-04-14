"""Project configuration loader for docgen.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_YAML_FILENAME = "docgen.yaml"


@dataclass
class Config:
    """Parsed and validated project configuration."""

    yaml_path: Path
    base_dir: Path
    raw: dict[str, Any]

    narration_dir: Path = field(init=False)
    audio_dir: Path = field(init=False)
    animations_dir: Path = field(init=False)
    terminal_dir: Path = field(init=False)
    recordings_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        dirs = self.raw.get("dirs", {})
        self.narration_dir = self.base_dir / dirs.get("narration", "narration")
        self.audio_dir = self.base_dir / dirs.get("audio", "audio")
        self.animations_dir = self.base_dir / dirs.get("animations", "animations")
        self.terminal_dir = self.base_dir / dirs.get("terminal", "terminal")
        self.recordings_dir = self.base_dir / dirs.get("recordings", "recordings")

    # -- Segment helpers -------------------------------------------------------

    @property
    def segments_default(self) -> list[str]:
        return self.raw.get("segments", {}).get("default", [])

    @property
    def segments_all(self) -> list[str]:
        return self.raw.get("segments", {}).get("all", self.segments_default)

    @property
    def segment_names(self) -> dict[str, str]:
        """Map segment ID → full name stem, e.g. {"01": "01-architecture"}."""
        return self.raw.get("segment_names", {})

    def resolve_segment_name(self, seg_id: str) -> str:
        """Return the full name for a segment, falling back to the ID itself."""
        return self.segment_names.get(seg_id, seg_id)

    @property
    def visual_map(self) -> dict[str, Any]:
        return self.raw.get("visual_map", {})

    @property
    def concat_map(self) -> dict[str, list[str]]:
        return self.raw.get("concat", {})

    # -- TTS -------------------------------------------------------------------

    @property
    def tts_model(self) -> str:
        return self.raw.get("tts", {}).get("model", "gpt-4o-mini-tts")

    @property
    def tts_voice(self) -> str:
        return self.raw.get("tts", {}).get("voice", "coral")

    @property
    def tts_instructions(self) -> str:
        return self.raw.get("tts", {}).get(
            "instructions",
            "You are narrating a technical demo video. Speak in a calm, professional tone.",
        )

    # -- Manim -----------------------------------------------------------------

    @property
    def manim_scenes(self) -> list[str]:
        return self.raw.get("manim", {}).get("scenes", [])

    @property
    def manim_quality(self) -> str:
        return self.raw.get("manim", {}).get("quality", "720p30")

    @property
    def manim_path(self) -> str | None:
        """Optional absolute/relative path to the Manim executable."""
        value = self.raw.get("manim", {}).get("manim_path")
        return str(value) if value else None

    @property
    def vhs_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "vhs_path": "",
            "sync_from_timing": False,
            "typing_ms_per_char": 35,
            "max_typing_sec": 3.0,
            "min_sleep_sec": 0.2,
        }
        defaults.update(self.raw.get("vhs", {}))
        return defaults

    @property
    def vhs_path(self) -> str | None:
        """Optional absolute/relative path to the VHS executable."""
        value = self.vhs_config.get("vhs_path")
        return str(value) if value else None

    @property
    def sync_from_timing(self) -> bool:
        return bool(self.vhs_config.get("sync_from_timing", False))

    @property
    def typing_ms_per_char(self) -> int:
        return int(self.vhs_config.get("typing_ms_per_char", 35))

    @property
    def max_typing_sec(self) -> float:
        return float(self.vhs_config.get("max_typing_sec", 3.0))

    @property
    def min_sleep_sec(self) -> float:
        return float(self.vhs_config.get("min_sleep_sec", 0.2))

    @property
    def sync_vhs_after_timestamps(self) -> bool:
        pipeline_cfg = self.raw.get("pipeline", {})
        if "sync_vhs_after_timestamps" in pipeline_cfg:
            return bool(pipeline_cfg.get("sync_vhs_after_timestamps"))
        return self.sync_from_timing

    # -- Compose ----------------------------------------------------------------

    @property
    def compose_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "ffmpeg_timeout_sec": 300,
            "warn_stale_vhs": True,
        }
        defaults.update(self.raw.get("compose", {}))
        return defaults

    @property
    def ffmpeg_timeout_sec(self) -> int:
        value = self.compose_config.get("ffmpeg_timeout_sec", 300)
        return int(value)

    @property
    def warn_stale_vhs(self) -> bool:
        return bool(self.compose_config.get("warn_stale_vhs", True))

    # -- Validation ------------------------------------------------------------

    @property
    def max_drift_sec(self) -> float:
        return float(self.raw.get("validation", {}).get("max_drift_sec", 2.75))

    @property
    def max_freeze_ratio(self) -> float:
        """Maximum fraction of a composed video that may be a frozen last frame."""
        return float(self.raw.get("validation", {}).get("max_freeze_ratio", 0.25))

    @property
    def ocr_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "sample_interval_sec": 2,
            "error_patterns": [
                "command not found",
                "No such file",
                "syntax error",
                "Permission denied",
                "bash:",
                r"\(\.venv\).*\(\.venv\)",
            ],
            "min_confidence": 40,
        }
        defaults.update(self.raw.get("validation", {}).get("ocr", {}))
        return defaults

    @property
    def layout_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "min_spacing_px": 10,
            "edge_margin_px": 15,
            "check_overlap": True,
        }
        defaults.update(self.raw.get("validation", {}).get("layout", {}))
        return defaults

    @property
    def av_sync_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "enabled": True,
            "tolerance_sec": 3.0,
            "min_anchors_per_segment": 2,
        }
        defaults.update(self.raw.get("validation", {}).get("av_sync", {}))
        return defaults

    @property
    def narration_lint_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "pre_tts_deny_patterns": [
                "target duration",
                "intended length",
                "visual:",
                "edit for voice",
                r"approximately \d+ minutes",
            ],
            "post_tts_deny_patterns": [
                "target duration",
                "narration segment",
                "script section",
                "edit for voice",
            ],
            "block_tts_on_pre_lint": True,
            "whisper_check": True,
        }
        defaults.update(self.raw.get("validation", {}).get("narration_lint", {}))
        return defaults

    # -- Pages -----------------------------------------------------------------

    @property
    def pages_config(self) -> dict[str, Any]:
        return self.raw.get("pages", {})

    # -- Wizard ----------------------------------------------------------------

    @property
    def wizard_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "llm_model": "gpt-4o",
            "system_prompt": (
                "You are a technical writer creating narration scripts for demo videos. "
                "Write in plain spoken English suitable for text-to-speech. No markdown "
                "formatting, no headings, no bullet points. Conversational but professional "
                "tone, like a senior engineer presenting at a conference."
            ),
            "default_guidance": "",
            "exclude_patterns": [
                "**/node_modules/**",
                "**/.pytest_cache/**",
                "**/archive/**",
                "**/__pycache__/**",
            ],
        }
        defaults.update(self.raw.get("wizard", {}))
        return defaults

    # -- Env file --------------------------------------------------------------

    @property
    def env_file(self) -> Path | None:
        rel = self.raw.get("env_file")
        if rel:
            return self.base_dir / rel
        return None

    # -- Repo root (for wizard scanning) ---------------------------------------

    @property
    def repo_root(self) -> Path:
        explicit = self.raw.get("repo_root")
        if explicit:
            return (self.base_dir / explicit).resolve()
        cur = self.base_dir.resolve()
        while cur != cur.parent:
            if (cur / ".git").exists():
                return cur
            cur = cur.parent
        return self.base_dir.resolve()

    # -- Factory methods -------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        path = Path(path).resolve()
        if path.is_dir():
            path = path / _YAML_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(yaml_path=path, base_dir=path.parent, raw=raw)

    @classmethod
    def discover(cls, start: str | Path | None = None) -> "Config":
        """Walk up from *start* (default cwd) looking for docgen.yaml."""
        cur = Path(start or os.getcwd()).resolve()
        while cur != cur.parent:
            candidate = cur / _YAML_FILENAME
            if candidate.exists():
                return cls.from_yaml(candidate)
            cur = cur.parent
        raise FileNotFoundError(
            f"Could not find {_YAML_FILENAME} in any parent of {start or os.getcwd()}"
        )
