"""Project configuration loader for docgen.yaml."""

from __future__ import annotations

import os
import re
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
    hints_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        dirs = self.raw.get("dirs", {})
        self.narration_dir = self.base_dir / dirs.get("narration", "narration")
        self.audio_dir = self.base_dir / dirs.get("audio", "audio")
        self.animations_dir = self.base_dir / dirs.get("animations", "animations")
        self.terminal_dir = self.base_dir / dirs.get("terminal", "terminal")
        self.recordings_dir = self.base_dir / dirs.get("recordings", "recordings")
        self.hints_dir = self.base_dir / dirs.get("hints", "hints")

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

    def narration_topic_label(self, seg_id: str) -> str:
        """Human-facing focus line for narration LLM prompts (no numeric segment ids).

        Prefer ``pages.segments.<id>.title``, then ``narration_from_source.segments.<id>.topic``,
        then the segment stem with a leading ``NN-`` / ``NN_`` prefix removed. Internal ids and
        file names stay in ``segment_names``; spoken scripts should not mention them.
        """
        sid = str(seg_id)
        pages = self.raw.get("pages")
        if isinstance(pages, dict):
            segs = pages.get("segments")
            if isinstance(segs, dict):
                block = segs.get(sid) or segs.get(seg_id)
                if isinstance(block, dict):
                    t = block.get("title")
                    if isinstance(t, str) and t.strip():
                        return t.strip()
        nfs = self.raw.get("narration_from_source")
        if isinstance(nfs, dict):
            seg_map = nfs.get("segments")
            if isinstance(seg_map, dict):
                seg_cfg = seg_map.get(sid) or seg_map.get(seg_id)
                if isinstance(seg_cfg, dict):
                    topic = seg_cfg.get("topic")
                    if isinstance(topic, str) and topic.strip():
                        return topic.strip()
        stem = str(self.resolve_segment_name(sid))
        cleaned = re.sub(r"^\d{2}[-_]", "", stem).strip("-_").strip()
        if cleaned and not re.fullmatch(r"\d+", cleaned):
            return cleaned
        return "Following the on-screen workflow"

    @property
    def visual_map(self) -> dict[str, Any]:
        return self.raw.get("visual_map", {})

    def pipeline_manim_scene_names(self) -> list[str]:
        """Scene class names for ``segments.all`` entries whose ``visual_map`` type is ``manim``."""
        seen: set[str] = set()
        ordered: list[str] = []
        for seg_id in self.segments_all:
            vm = self.visual_map.get(seg_id)
            if not isinstance(vm, dict):
                continue
            if str(vm.get("type", "")).lower() != "manim":
                continue
            scene = str(vm.get("scene", "")).strip()
            if scene and scene not in seen:
                seen.add(scene)
                ordered.append(scene)
        return ordered

    def pipeline_vhs_tape_filenames(self) -> list[str]:
        """Tape filenames for ``segments.all`` entries whose ``visual_map`` type is ``vhs``."""
        ordered: list[str] = []
        for seg_id in self.segments_all:
            vm = self.visual_map.get(seg_id)
            if not isinstance(vm, dict):
                continue
            if str(vm.get("type", "")).lower() != "vhs":
                continue
            tape = str(vm.get("tape", "")).strip()
            if not tape:
                src = str(vm.get("source", "")).strip()
                if src:
                    tape = f"{Path(src).stem}.tape"
            if tape:
                ordered.append(tape)
        return ordered

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
        return self.raw.get("manim", {}).get("quality", "1080p30")

    @property
    def manim_font(self) -> str:
        """Font family used for all Manim Text() calls (default: Liberation Sans)."""
        return str(self.raw.get("manim", {}).get("font", "Liberation Sans"))

    @property
    def manim_min_font_size(self) -> int:
        """Minimum font size enforced in Manim scene lint (default: 14)."""
        return int(self.raw.get("manim", {}).get("min_font_size", 14))

    @property
    def manim_scene_lint_enabled(self) -> bool:
        """When false, ``docgen validate`` skips Text()/unicode lint on ``animations/scenes.py``."""
        return bool(self.raw.get("manim", {}).get("scene_lint", True))

    @property
    def manim_path(self) -> str | None:
        """Optional absolute/relative path to the Manim executable."""
        value = self.raw.get("manim", {}).get("manim_path")
        return str(value) if value else None

    @property
    def manim_unsafe_unicode(self) -> list[str]:
        """Unicode characters that trigger Pango font fallback."""
        default = ["\u2192", "\u2190", "\u2194", "\u203a", "\u2039",
                   "\u2260", "\u2264", "\u2265", "\u2014", "\u2013",
                   "\u2018", "\u2019", "\u201c", "\u201d", "\u2022",
                   "\u2026"]
        return self.raw.get("manim", {}).get("unsafe_unicode", default)

    @property
    def vhs_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "vhs_path": "",
            "sync_from_timing": False,
            "typing_ms_per_char": 35,
            "max_typing_sec": 3.0,
            "min_sleep_sec": 0.2,
            "render_timeout_sec": 120,
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
    def vhs_render_timeout_sec(self) -> int:
        return int(self.vhs_config.get("render_timeout_sec", 120))

    @property
    def sync_vhs_after_timestamps(self) -> bool:
        pipeline_cfg = self.raw.get("pipeline", {})
        if "sync_vhs_after_timestamps" in pipeline_cfg:
            return bool(pipeline_cfg.get("sync_vhs_after_timestamps"))
        return self.sync_from_timing

    # -- Playwright ------------------------------------------------------------

    @property
    def playwright_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "python_path": "",
            "timeout_sec": 120,
            "default_url": "",
            "default_viewport": {"width": 1920, "height": 1080},
        }
        defaults.update(self.raw.get("playwright", {}))
        return defaults

    @property
    def playwright_python_path(self) -> str | None:
        value = self.playwright_config.get("python_path")
        return str(value) if value else None

    @property
    def playwright_timeout_sec(self) -> int:
        return int(self.playwright_config.get("timeout_sec", 120))

    @property
    def playwright_default_url(self) -> str | None:
        value = str(self.playwright_config.get("default_url", "")).strip()
        return value or None

    @property
    def playwright_default_viewport(self) -> tuple[int, int]:
        raw = self.playwright_config.get("default_viewport", {}) or {}
        width = int(raw.get("width", 1920))
        height = int(raw.get("height", 1080))
        return width, height

    # -- Playwright test video (visual_map type: playwright_test) ---------------

    @property
    def playwright_test_config(self) -> dict[str, Any]:
        """YAML `playwright_test:` block — test runner dirs, speed limits, etc."""
        defaults: dict[str, Any] = {
            "min_speed_factor": 0.25,
            "max_speed_factor": 4.0,
        }
        raw = self.raw.get("playwright_test")
        if isinstance(raw, dict):
            defaults.update(raw)
        return defaults

    @property
    def playwright_test_min_speed_factor(self) -> float:
        return float(self.playwright_test_config.get("min_speed_factor", 0.25))

    @property
    def playwright_test_max_speed_factor(self) -> float:
        return float(self.playwright_test_config.get("max_speed_factor", 4.0))

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

    def effective_max_freeze_ratio(self, visual_type: str | None) -> float:
        """Ceiling for compose-time audio-vs-video freeze guard (trailing pad).

        For ``playwright`` / ``playwright_test``, the default global
        ``max_freeze_ratio`` (0.25) is raised to at least **0.45** so short UI
        capture + longer TTS is less likely to fail on first run. Set
        ``validation.max_freeze_ratio_playwright`` to override that family only.
        """
        base = self.max_freeze_ratio
        rawv = self.raw.get("validation", {})
        vt = (visual_type or "").strip().lower()
        if vt in ("playwright", "playwright_test"):
            if "max_freeze_ratio_playwright" in rawv:
                return float(rawv["max_freeze_ratio_playwright"])
            return max(base, 0.45)
        return base

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

    @property
    def discover_tests_scan_roots(self) -> list[Path]:
        """Directories to scan for Node Playwright projects (each may have its own ``package.json``).

        YAML (``discover_tests.roots``) lists paths **relative to** :meth:`repo_root`. Default is a
        single entry ``["."]`` (repo root). Monorepos can set e.g. ``[".", "apps/web"]``.
        """
        rr = self.repo_root.resolve()
        block = self.raw.get("discover_tests")
        if not isinstance(block, dict):
            return [rr]
        roots = block.get("roots")
        if not roots:
            return [rr]
        out: list[Path] = []
        for r in roots:
            p = (rr / str(r).strip()).resolve()
            out.append(p)
        return out

    @property
    def catalog_file_path(self) -> Path:
        """YAML catalog of discovered sources (``docgen catalog`` / future discover-tests).

        **Default (stable across projects):** ``<repo_root>/docgen.catalog.yaml`` where
        ``repo_root`` is the same path as :meth:`repo_root` (nearest ``.git`` directory,
        or the ``repo_root:`` key in ``docgen.yaml``). Keeping the catalog at the repo
        root avoids moving it when ``docgen.yaml`` lives under ``docs/demos/`` etc., and
        gives CI one canonical file to commit for incremental regeneration.

        **Override:** set ``catalog.file`` to an absolute path, or a path **relative to
        ``repo_root``** (not relative to ``docgen.yaml``'s directory).

        .. code-block:: yaml

            catalog:
              file: docs/docgen.catalog.yaml   # under repo_root
        """
        root = self.repo_root
        cat = self.raw.get("catalog")
        if isinstance(cat, dict) and cat.get("file"):
            p = Path(str(cat["file"]))
            return p.resolve() if p.is_absolute() else (root / p).resolve()
        return (root / "docgen.catalog.yaml").resolve()

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

    @classmethod
    def minimal(cls, base_dir: str | Path | None = None) -> "Config":
        """Minimal config when no ``docgen.yaml`` exists (standalone tools).

        Relative tape paths and Playwright discovery resolve under ``base_dir``
        (defaults to the current working directory).
        """
        base = Path(base_dir or os.getcwd()).resolve()
        return cls(yaml_path=base / _YAML_FILENAME, base_dir=base, raw={})
