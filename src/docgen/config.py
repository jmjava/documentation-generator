"""Project configuration loader for docgen.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_YAML_FILENAME = "docgen.yaml"


class ConfigError(ValueError):
    """Raised when ``docgen.yaml`` cannot be parsed as a mapping."""


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load *path* as a YAML mapping.

    An empty document becomes ``{}``. Invalid YAML or a non-mapping root
    (list, scalar) raises :class:`ConfigError`.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path.name} root must be a YAML mapping, not {type(raw).__name__}"
        )
    return raw


def mapping_block(
    raw: dict[str, Any],
    key: str,
    *,
    label: str | None = None,
    source: str = "docgen.yaml",
) -> dict[str, Any]:
    """Return ``raw[key]`` when it is a mapping; ``{}`` when missing or null.

    A non-mapping value (list, scalar) raises :class:`ConfigError`.
    """
    name = label or key
    val = raw.get(key)
    if val is None:
        return {}
    if not isinstance(val, dict):
        raise ConfigError(
            f"{source}: {name} must be a YAML mapping, not {type(val).__name__}"
        )
    return val


def mapping_sub_block(
    parent: dict[str, Any],
    key: str,
    *,
    label: str,
    source: str = "docgen.yaml",
) -> dict[str, Any]:
    """Return ``parent[key]`` when it is a mapping; ``{}`` when missing or null."""
    val = parent.get(key)
    if val is None:
        return {}
    if not isinstance(val, dict):
        raise ConfigError(
            f"{source}: {label} must be a YAML mapping, not {type(val).__name__}"
        )
    return val


def require_optional_yaml_string(value: Any, *, label: str, source: str) -> None:
    """Allow missing/null; a present value must be a YAML string (empty OK)."""
    if value is not None and not isinstance(value, str):
        raise ConfigError(
            f"{source}: {label} must be a YAML string, not {type(value).__name__}"
        )


def require_yaml_bool(value: Any, *, label: str, source: str) -> bool:
    """Require a YAML boolean so ``0`` / ``\"false\"`` are not misread as off/on.

    Identity checks like ``value is False`` are false for integer ``0`` and
    the string ``\"false\"``, which used to leave ``discovery.auto_visual_map``
    enabled and rewrite ``visual_map``.
    """
    if isinstance(value, bool):
        return value
    raise ConfigError(
        f"{source}: {label} must be a YAML boolean, not {type(value).__name__} "
        f"({value!r})"
    )


def require_yaml_number(value: Any, *, label: str, source: str) -> float:
    """Require a YAML number so lists/strings/bools do not reach ``int()``/``float()``.

    ``bool`` is a subclass of ``int``: ``compose.ffmpeg_timeout_sec: true``
    used to become timeout ``1`` (second), and ``manim.min_font_size: true``
    became font size ``1``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"{source}: {label} must be a YAML number, not {type(value).__name__} "
            f"({value!r})"
        )
    return float(value)


def require_yaml_string(value: Any, *, label: str, source: str) -> str:
    """Require a YAML string so unquoted ``01`` is not silently coerced to ``\"1\"``."""
    if isinstance(value, str):
        if not value.strip():
            raise ConfigError(f"{source}: {label} must be a non-empty string")
        return value
    raise ConfigError(
        f"{source}: {label} must be a YAML string, not {type(value).__name__} "
        f"({value!r}). Unquoted 01 is integer 1; write \"01\"."
    )


def string_list_block(
    raw: dict[str, Any],
    key: str,
    *,
    fallback: list[str] | None = None,
    label: str | None = None,
    source: str = "docgen.yaml",
) -> list[str]:
    """Return a list of strings from ``raw[key]``, or *fallback* when missing/null."""
    name = label or key
    val = raw.get(key)
    if val is None:
        return list(fallback or [])
    if not isinstance(val, list):
        raise ConfigError(
            f"{source}: {name} must be a YAML list, not {type(val).__name__}"
        )
    return [
        require_yaml_string(x, label=f"{name}[{i}]", source=source)
        for i, x in enumerate(val)
    ]


def require_hint_and_context_lists(
    block: dict[str, Any],
    *,
    prefix: str,
    source: str,
) -> None:
    """Fail closed when hints/context.paths/globs or per-segment blocks have the wrong YAML type."""
    if block.get("hints") is not None:
        string_list_block(block, "hints", label=f"{prefix}.hints", source=source)
    ctx = block.get("context")
    if ctx is not None:
        if not isinstance(ctx, dict):
            raise ConfigError(
                f"{source}: {prefix}.context must be a YAML mapping, not {type(ctx).__name__}"
            )
        string_list_block(ctx, "paths", label=f"{prefix}.context.paths", source=source)
        string_list_block(ctx, "globs", label=f"{prefix}.context.globs", source=source)
    segs = block.get("segments")
    if segs is None:
        return
    if not isinstance(segs, dict):
        raise ConfigError(
            f"{source}: {prefix}.segments must be a YAML mapping, not {type(segs).__name__}"
        )
    for sid, spec in segs.items():
        sid_s = require_yaml_string(sid, label=f"{prefix}.segments key", source=source)
        if spec is None:
            continue
        if not isinstance(spec, dict):
            raise ConfigError(
                f"{source}: {prefix}.segments.{sid_s} must be a YAML mapping, "
                f"not {type(spec).__name__}"
            )
        require_optional_yaml_string(
            spec.get("system_prompt"),
            label=f"{prefix}.segments.{sid_s}.system_prompt",
            source=source,
        )
        require_optional_yaml_string(
            spec.get("topic"),
            label=f"{prefix}.segments.{sid_s}.topic",
            source=source,
        )
        require_optional_yaml_string(
            spec.get("scene_spec_system_prompt"),
            label=f"{prefix}.segments.{sid_s}.scene_spec_system_prompt",
            source=source,
        )
        if spec.get("class_name") is not None:
            require_yaml_string(
                spec["class_name"],
                label=f"{prefix}.segments.{sid_s}.class_name",
                source=source,
            )
        require_hint_and_context_lists(spec, prefix=f"{prefix}.segments.{sid_s}", source=source)


@dataclass
class Config:
    """Parsed and validated project configuration."""

    yaml_path: Path
    base_dir: Path
    raw: dict[str, Any]

    narration_dir: Path = field(init=False)
    audio_dir: Path = field(init=False)
    animations_dir: Path = field(init=False)
    recordings_dir: Path = field(init=False)
    hints_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        src = self._source_label()
        dirs = self._block("dirs")
        for dkey in ("narration", "audio", "animations", "recordings", "hints"):
            if dirs.get(dkey) is not None:
                require_yaml_string(dirs[dkey], label=f"dirs.{dkey}", source=src)
        self.narration_dir = self.base_dir / dirs.get("narration", "narration")
        self.audio_dir = self.base_dir / dirs.get("audio", "audio")
        self.animations_dir = self.base_dir / dirs.get("animations", "animations")
        self.recordings_dir = self.base_dir / dirs.get("recordings", "recordings")
        self.hints_dir = self.base_dir / dirs.get("hints", "hints")
        # Fail closed on nested mapping keys so later properties do not traceback.
        for key in (
            "dirs",
            "segments",
            "visual_map",
            "segment_names",
            "tts",
            "manim",
            "validation",
            "wizard",
            "pages",
            "concat",
            "compose",
            "timestamps",
            "image_generation",
            "ai",
            "narration_from_source",
            "manim_scene_generation",
            "discovery",
        ):
            self._block(key)
        validation = self._block("validation")
        for nested in (
            "ocr",
            "layout",
            "av_sync",
            "timing_sync",
            "scene_assets",
            "story_end",
            "narration_lint",
            "subject_beat_coverage",
        ):
            self._sub_block(validation, nested, label=f"validation.{nested}")
        # List-valued keys: a string must not be iterated as characters.
        _ = self.segments_all
        _ = self.manim_scenes
        _ = self.manim_unsafe_unicode
        concat = self._block("concat")
        src = self._source_label()
        for name, segs in concat.items():
            if segs is None:
                continue
            if not isinstance(segs, list):
                raise ConfigError(
                    f"{src}: concat.{name} must be a YAML list, "
                    f"not {type(segs).__name__}"
                )
            for i, item in enumerate(segs):
                require_yaml_string(item, label=f"concat.{name}[{i}]", source=src)
        for key, val in self._block("segment_names").items():
            sid = require_yaml_string(key, label="segment_names key", source=src)
            require_yaml_string(val, label=f"segment_names.{sid}", source=src)
        pages = self._block("pages")
        if pages.get("docs_dir") is not None:
            require_yaml_string(pages["docs_dir"], label="pages.docs_dir", source=src)
        if pages.get("demos_subdir") is not None:
            require_yaml_string(pages["demos_subdir"], label="pages.demos_subdir", source=src)
        require_optional_yaml_string(pages.get("title"), label="pages.title", source=src)
        require_optional_yaml_string(pages.get("subtitle"), label="pages.subtitle", source=src)
        require_optional_yaml_string(pages.get("repo_url"), label="pages.repo_url", source=src)
        extra_links = pages.get("extra_links")
        if extra_links is not None:
            if not isinstance(extra_links, list):
                raise ConfigError(
                    f"{src}: pages.extra_links must be a YAML list, "
                    f"not {type(extra_links).__name__}"
                )
            for i, item in enumerate(extra_links):
                if not isinstance(item, dict):
                    raise ConfigError(
                        f"{src}: pages.extra_links[{i}] must be a YAML mapping, "
                        f"not {type(item).__name__}"
                    )
                require_yaml_string(
                    item.get("href"),
                    label=f"pages.extra_links[{i}].href",
                    source=src,
                )
                require_optional_yaml_string(
                    item.get("label"),
                    label=f"pages.extra_links[{i}].label",
                    source=src,
                )
        pages_segs = pages.get("segments")
        if pages_segs is not None and not isinstance(pages_segs, dict):
            raise ConfigError(
                f"{src}: pages.segments must be a YAML mapping, not {type(pages_segs).__name__}"
            )
        if isinstance(pages_segs, dict):
            for key, spec in pages_segs.items():
                sid = require_yaml_string(key, label="pages.segments key", source=src)
                if spec is None:
                    continue
                if not isinstance(spec, dict):
                    raise ConfigError(
                        f"{src}: pages.segments.{sid} must be a YAML mapping, "
                        f"not {type(spec).__name__}"
                    )
                require_optional_yaml_string(
                    spec.get("title"),
                    label=f"pages.segments.{sid}.title",
                    source=src,
                )
                require_optional_yaml_string(
                    spec.get("description"),
                    label=f"pages.segments.{sid}.description",
                    source=src,
                )
        require_hint_and_context_lists(
            self._block("narration_from_source"),
            prefix="narration_from_source",
            source=src,
        )
        require_hint_and_context_lists(
            self._block("manim_scene_generation"),
            prefix="manim_scene_generation",
            source=src,
        )
        vm = self._block("visual_map")
        for sid, spec in vm.items():
            sid_s = require_yaml_string(sid, label="visual_map key", source=src)
            if spec is None:
                continue
            if not isinstance(spec, dict):
                raise ConfigError(
                    f"{src}: visual_map.{sid_s} must be a YAML mapping, "
                    f"not {type(spec).__name__}"
                )
            for fname in ("type", "scene", "class", "source"):
                val = spec.get(fname)
                if val is not None and not isinstance(val, str):
                    raise ConfigError(
                        f"{src}: visual_map.{sid_s}.{fname} must be a YAML string, "
                        f"not {type(val).__name__}"
                    )
            if spec.get("sources") is not None:
                string_list_block(
                    spec,
                    "sources",
                    label=f"visual_map.{sid_s}.sources",
                    source=src,
                )
        wiz = self._block("wizard")
        if wiz.get("exclude_patterns") is not None:
            string_list_block(
                wiz,
                "exclude_patterns",
                label="wizard.exclude_patterns",
                source=src,
            )
        if wiz.get("scan_extensions") is not None:
            string_list_block(
                wiz,
                "scan_extensions",
                label="wizard.scan_extensions",
                source=src,
            )
        tts = self._block("tts")
        if tts.get("model") is not None:
            require_yaml_string(tts["model"], label="tts.model", source=src)
        if tts.get("voice") is not None:
            require_yaml_string(tts["voice"], label="tts.voice", source=src)
        inst = tts.get("instructions")
        if inst is not None and not isinstance(inst, str):
            raise ConfigError(
                f"{src}: tts.instructions must be a YAML string, "
                f"not {type(inst).__name__}"
            )
        if wiz.get("system_prompt") is not None:
            require_optional_yaml_string(
                wiz["system_prompt"], label="wizard.system_prompt", source=src
            )
        if wiz.get("default_guidance") is not None:
            require_optional_yaml_string(
                wiz["default_guidance"], label="wizard.default_guidance", source=src
            )
        if wiz.get("llm_model") is not None:
            require_yaml_string(wiz["llm_model"], label="wizard.llm_model", source=src)
        ig = self._block("image_generation")
        if ig.get("model") is not None:
            require_yaml_string(ig["model"], label="image_generation.model", source=src)
        if ig.get("size") is not None:
            require_yaml_string(ig["size"], label="image_generation.size", source=src)
        if ig.get("quality") is not None:
            require_yaml_string(ig["quality"], label="image_generation.quality", source=src)
        ai = self._block("ai")
        if ai.get("provider") is not None:
            require_yaml_string(ai["provider"], label="ai.provider", source=src)
        if ai.get("base_url") is not None:
            require_yaml_string(ai["base_url"], label="ai.base_url", source=src)
        if ai.get("api_key_env") is not None:
            require_yaml_string(ai["api_key_env"], label="ai.api_key_env", source=src)
        ts = self._block("timestamps")
        if ts.get("engine") is not None:
            require_yaml_string(ts["engine"], label="timestamps.engine", source=src)
        if ts.get("silence_noise_db") is not None:
            require_yaml_number(
                ts["silence_noise_db"],
                label="timestamps.silence_noise_db",
                source=src,
            )
        if ts.get("min_silence_sec") is not None:
            require_yaml_number(
                ts["min_silence_sec"],
                label="timestamps.min_silence_sec",
                source=src,
            )
        if tts.get("language") is not None:
            require_yaml_string(tts["language"], label="tts.language", source=src)
        manim = self._block("manim")
        if manim.get("font") is not None:
            require_yaml_string(manim["font"], label="manim.font", source=src)
        if manim.get("quality") is not None:
            require_yaml_string(manim["quality"], label="manim.quality", source=src)
        if manim.get("manim_path") is not None:
            require_yaml_string(manim["manim_path"], label="manim.manim_path", source=src)
        if manim.get("min_font_size") is not None:
            require_yaml_number(
                manim["min_font_size"],
                label="manim.min_font_size",
                source=src,
            )
        compose = self._block("compose")
        if compose.get("ffmpeg_timeout_sec") is not None:
            require_yaml_number(
                compose["ffmpeg_timeout_sec"],
                label="compose.ffmpeg_timeout_sec",
                source=src,
            )
        if validation.get("max_drift_sec") is not None:
            require_yaml_number(
                validation["max_drift_sec"],
                label="validation.max_drift_sec",
                source=src,
            )
        if validation.get("max_freeze_ratio") is not None:
            require_yaml_number(
                validation["max_freeze_ratio"],
                label="validation.max_freeze_ratio",
                source=src,
            )
        nfs = self._block("narration_from_source")
        if nfs.get("model") is not None:
            require_yaml_string(
                nfs["model"], label="narration_from_source.model", source=src
            )
        if nfs.get("system_prompt") is not None:
            require_optional_yaml_string(
                nfs["system_prompt"],
                label="narration_from_source.system_prompt",
                source=src,
            )
        msg = self._block("manim_scene_generation")
        if msg.get("model") is not None:
            require_yaml_string(
                msg["model"], label="manim_scene_generation.model", source=src
            )
        if msg.get("system_prompt") is not None:
            require_optional_yaml_string(
                msg["system_prompt"],
                label="manim_scene_generation.system_prompt",
                source=src,
            )
        if msg.get("scene_spec_system_prompt") is not None:
            require_optional_yaml_string(
                msg["scene_spec_system_prompt"],
                label="manim_scene_generation.scene_spec_system_prompt",
                source=src,
            )
        if self.raw.get("env_file") is not None:
            require_yaml_string(self.raw["env_file"], label="env_file", source=src)
        if self.raw.get("repo_root") is not None:
            require_yaml_string(self.raw["repo_root"], label="repo_root", source=src)
        disc = self._block("discovery")
        for dkey in ("auto_visual_map", "merge_hint_segments"):
            if disc.get(dkey) is not None:
                require_yaml_bool(
                    disc[dkey], label=f"discovery.{dkey}", source=src
                )
        ocr = self._sub_block(validation, "ocr", label="validation.ocr")
        if ocr.get("error_patterns") is not None:
            string_list_block(
                ocr,
                "error_patterns",
                label="validation.ocr.error_patterns",
                source=src,
            )
        avs = self._sub_block(validation, "av_sync", label="validation.av_sync")
        if avs.get("visual_types") is not None:
            string_list_block(
                avs,
                "visual_types",
                label="validation.av_sync.visual_types",
                source=src,
            )
        anchors = avs.get("anchor_keywords")
        if anchors is not None:
            if not isinstance(anchors, dict):
                raise ConfigError(
                    f"{src}: validation.av_sync.anchor_keywords must be a YAML mapping, "
                    f"not {type(anchors).__name__}"
                )
            for sid, rows in anchors.items():
                sid_s = require_yaml_string(
                    sid, label="validation.av_sync.anchor_keywords key", source=src
                )
                if rows is None:
                    continue
                if not isinstance(rows, list):
                    raise ConfigError(
                        f"{src}: validation.av_sync.anchor_keywords.{sid_s} must be a "
                        f"YAML list, not {type(rows).__name__}"
                    )
                for i, row in enumerate(rows):
                    if not isinstance(row, dict):
                        raise ConfigError(
                            f"{src}: validation.av_sync.anchor_keywords.{sid_s}[{i}] "
                            f"must be a YAML mapping, not {type(row).__name__}"
                        )
                    require_yaml_string(
                        row.get("keyword"),
                        label=f"validation.av_sync.anchor_keywords.{sid_s}[{i}].keyword",
                        source=src,
                    )
        nl = self._sub_block(validation, "narration_lint", label="validation.narration_lint")
        if nl.get("pre_tts_deny_patterns") is not None:
            string_list_block(
                nl,
                "pre_tts_deny_patterns",
                label="validation.narration_lint.pre_tts_deny_patterns",
                source=src,
            )
        if nl.get("post_tts_deny_patterns") is not None:
            string_list_block(
                nl,
                "post_tts_deny_patterns",
                label="validation.narration_lint.post_tts_deny_patterns",
                source=src,
            )

    def _source_label(self) -> str:
        return self.yaml_path.name if self.yaml_path else "docgen.yaml"

    def _block(self, key: str, *, label: str | None = None) -> dict[str, Any]:
        return mapping_block(self.raw, key, label=label, source=self._source_label())

    def _sub_block(self, parent: dict[str, Any], key: str, *, label: str) -> dict[str, Any]:
        return mapping_sub_block(parent, key, label=label, source=self._source_label())

    # -- Segment helpers -------------------------------------------------------

    @property
    def segments_default(self) -> list[str]:
        return string_list_block(
            self._block("segments"),
            "default",
            label="segments.default",
            source=self._source_label(),
        )

    @property
    def segments_all(self) -> list[str]:
        seg = self._block("segments")
        if "all" not in seg or seg.get("all") is None:
            return list(self.segments_default)
        return string_list_block(
            seg,
            "all",
            fallback=self.segments_default,
            label="segments.all",
            source=self._source_label(),
        )

    @property
    def segment_names(self) -> dict[str, str]:
        """Map segment ID → full name stem, e.g. {"01": "01-architecture"}."""
        return {str(k): str(v) for k, v in self._block("segment_names").items()}

    def resolve_segment_name(self, seg_id: str) -> str:
        """Return the full name for a segment, falling back to the ID itself."""
        return self.segment_names.get(seg_id, seg_id)

    def find_segment_asset(self, directory: Path, seg_id: str, suffix: str) -> Path | None:
        """Resolve a per-segment file without substring glob collisions (``01`` vs ``101``).

        Prefers ``segment_names[id]`` stem. If the stem is the id itself, also
        accepts ``{id}-*{suffix}``. Does not use ``*{id}*`` and does not treat
        a bare ``{id}{suffix}`` as a match for a longer stem (orphan ``01.mp3``
        must not satisfy segment ``01-intro``).
        """
        if not directory.is_dir():
            return None
        sid = str(seg_id)
        ext = suffix if suffix.startswith(".") else f".{suffix}"
        stem = str(self.resolve_segment_name(sid))
        exact = directory / f"{stem}{ext}"
        if exact.is_file():
            return exact
        if stem != sid:
            return None
        prefixed = sorted(p for p in directory.glob(f"{sid}-*{ext}") if p.is_file())
        return prefixed[0] if prefixed else None

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
        return self._block("visual_map")

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
            scene = str(vm.get("scene", "")).strip() or str(vm.get("class", "")).strip()
            if scene and scene not in seen:
                seen.add(scene)
                ordered.append(scene)
        return ordered

    @property
    def concat_map(self) -> dict[str, list[str]]:
        return self._block("concat")

    # -- AI provider (OpenAI / Grok) ------------------------------------------

    @property
    def ai_config(self) -> dict[str, Any]:
        """``ai.provider`` plus optional ``base_url`` / ``api_key_env``.

        ``provider`` is ``openai`` (default), ``grok`` (xAI), or ``anthropic``
        (Claude chat). Environment ``DOCGEN_AI_PROVIDER`` overrides YAML. When
        omitted, a usable Cursor/OpenAI key keeps ``openai``; only
        ``ANTHROPIC_API_KEY`` selects Claude. See :mod:`docgen.ai_client`.
        """
        defaults: dict[str, Any] = {"provider": "openai"}
        block = self._block("ai")
        if block:
            defaults.update(block)
        return defaults

    # -- TTS -------------------------------------------------------------------

    @property
    def tts_model(self) -> str:
        return self._block("tts").get("model", "gpt-4o-mini-tts")

    @property
    def tts_voice(self) -> str:
        return self._block("tts").get("voice", "coral")

    @property
    def tts_instructions(self) -> str:
        return self._block("tts").get(
            "instructions",
            "You are narrating a technical demo video. Speak in a calm, professional tone.",
        )

    # -- Timestamps ---------------------------------------------------------------

    @property
    def timestamps_config(self) -> dict[str, Any]:
        """Engine + tuning for ``docgen timestamps``.

        ``engine: local`` (default) aligns the known narration text against the
        mp3 offline (ffmpeg silencedetect); ``engine: whisper`` transcribes via
        OpenAI whisper-1 (network + API key) or xAI STT when ``ai.provider`` is grok.
        """
        defaults: dict[str, Any] = {
            "engine": "local",
            "silence_noise_db": -35.0,
            "min_silence_sec": 0.3,
        }
        defaults.update(self._block("timestamps"))
        return defaults

    # -- Image generation (scene-spec image elements) ----------------------------

    @property
    def image_generation_config(self) -> dict[str, Any]:
        """Settings for ``docgen image-generate`` (OpenAI Images or xAI Imagine).

        ``quality`` is passed through only when set (model-specific values,
        e.g. ``low`` / ``medium`` / ``high`` for gpt-image-1).
        """
        defaults: dict[str, Any] = {
            "model": "gpt-image-1",
            "size": "1536x1024",
        }
        defaults.update(self._block("image_generation"))
        return defaults

    # -- Manim -----------------------------------------------------------------

    @property
    def manim_scenes(self) -> list[str]:
        return string_list_block(
            self._block("manim"),
            "scenes",
            label="manim.scenes",
            source=self._source_label(),
        )

    @property
    def manim_quality(self) -> str:
        return self._block("manim").get("quality", "1080p30")

    @property
    def manim_font(self) -> str:
        """Font family used for all Manim Text() calls (default: Liberation Sans)."""
        return str(self._block("manim").get("font", "Liberation Sans"))

    @property
    def manim_min_font_size(self) -> int:
        """Minimum font size enforced in Manim scene lint (default: 14)."""
        return int(self._block("manim").get("min_font_size", 14))

    @property
    def manim_scene_lint_enabled(self) -> bool:
        """When false, ``docgen validate`` skips Text()/unicode lint on ``animations/scenes.py``."""
        return bool(self._block("manim").get("scene_lint", True))

    @property
    def subject_beat_coverage_enabled(self) -> bool:
        """When true (default), validate + scene-spec-generate enforce subject-beat coverage.

        Config: ``validation.subject_beat_coverage.enabled`` (bool).
        """
        block = self._sub_block(
            self._block("validation"), "subject_beat_coverage", label="validation.subject_beat_coverage"
        )
        if "enabled" in block:
            return bool(block.get("enabled"))
        return True

    @property
    def manim_path(self) -> str | None:
        """Optional absolute/relative path to the Manim executable."""
        value = self._block("manim").get("manim_path")
        return str(value) if value else None

    @property
    def manim_unsafe_unicode(self) -> list[str]:
        """Unicode characters that trigger Pango font fallback."""
        default = ["\u2192", "\u2190", "\u2194", "\u203a", "\u2039",
                   "\u2260", "\u2264", "\u2265", "\u2014", "\u2013",
                   "\u2018", "\u2019", "\u201c", "\u201d", "\u2022",
                   "\u2026"]
        return string_list_block(
            self._block("manim"),
            "unsafe_unicode",
            fallback=default,
            label="manim.unsafe_unicode",
            source=self._source_label(),
        )

    # -- Compose ----------------------------------------------------------------

    @property
    def compose_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "ffmpeg_timeout_sec": 300,
        }
        defaults.update(self._block("compose"))
        return defaults

    @property
    def ffmpeg_timeout_sec(self) -> int:
        value = self.compose_config.get("ffmpeg_timeout_sec", 300)
        return int(value)

    # -- Validation ------------------------------------------------------------

    @property
    def max_drift_sec(self) -> float:
        return float(self._block("validation").get("max_drift_sec", 2.75))

    @property
    def max_freeze_ratio(self) -> float:
        """Maximum fraction of a composed video that may be a frozen last frame."""
        return float(self._block("validation").get("max_freeze_ratio", 0.25))

    def effective_max_freeze_ratio(self, visual_type: str | None) -> float:
        """Ceiling for compose-time audio-vs-video freeze guard (trailing pad)."""
        return self.max_freeze_ratio

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
        defaults.update(self._sub_block(self._block("validation"), "ocr", label="validation.ocr"))
        return defaults

    @property
    def layout_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "min_spacing_px": 10,
            "edge_margin_px": 15,
            "check_overlap": True,
        }
        defaults.update(
            self._sub_block(self._block("validation"), "layout", label="validation.layout")
        )
        return defaults

    @property
    def av_sync_config(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "enabled": True,
            "tolerance_sec": 3.0,
            "min_anchors_per_segment": 2,
            "max_anchors_per_segment": 8,
            # Prefer scene-spec box labels as OCR anchors when specs exist.
            "prefer_scene_spec_labels": True,
            # Only OCR-anchor these visual types (on-screen text expected).
            "visual_types": ["manim"],
        }
        defaults.update(
            self._sub_block(self._block("validation"), "av_sync", label="validation.av_sync")
        )
        return defaults

    @property
    def timing_sync_config(self) -> dict[str, Any]:
        """Audio ↔ timing.json consistency check (``docgen validate`` ``timing_sync``).

        ``max_tail_gap_sec``: how much longer the mp3 may run past the last
        transcribed word/segment end before timing.json is considered stale.
        ``max_end_overrun_sec``: how far the transcript may extend past the mp3
        duration (stale timing from a longer, older take).
        """
        defaults: dict[str, Any] = {
            "enabled": True,
            "max_tail_gap_sec": 3.0,
            "max_end_overrun_sec": 1.0,
        }
        defaults.update(
            self._sub_block(
                self._block("validation"), "timing_sync", label="validation.timing_sync"
            )
        )
        return defaults

    @property
    def scene_assets_config(self) -> dict[str, Any]:
        """Pre-render checks for stuck boards, overlaps, fonts, and compile sync.

        Runs in ``docgen validate`` (hard fail in ``--pre-push``) and as a
        ``generate-all`` gate before Manim so a stale spec cannot burn a render.
        """
        defaults: dict[str, Any] = {"enabled": True}
        defaults.update(
            self._sub_block(
                self._block("validation"), "scene_assets", label="validation.scene_assets"
            )
        )
        return defaults

    @property
    def story_end_config(self) -> dict[str, Any]:
        """Visual story finished early vs narration (``docgen validate`` ``story_end``).

        Compares the last paced scene-spec reveal (label→``wait_word`` start) to
        the audio/transcript end. Fails when idle time after the last reveal
        exceeds **both** ``max_early_sec`` and ``max_early_ratio`` × audio end
        (hard fail in ``--pre-push``, like ``timing_sync``).
        """
        defaults: dict[str, Any] = {
            "enabled": True,
            "max_early_sec": 40.0,
            "max_early_ratio": 0.45,
        }
        defaults.update(
            self._sub_block(self._block("validation"), "story_end", label="validation.story_end")
        )
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
        defaults.update(
            self._sub_block(
                self._block("validation"), "narration_lint", label="validation.narration_lint"
            )
        )
        return defaults

    # -- Pages -----------------------------------------------------------------

    @property
    def pages_config(self) -> dict[str, Any]:
        return self._block("pages")

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
            # Extensions offered in the wizard file tree for focus selection.
            "scan_extensions": [
                ".md",
                ".py",
                ".yaml",
                ".yml",
                ".toml",
                ".json",
                ".txt",
                ".rst",
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".go",
                ".rs",
                ".java",
            ],
        }
        defaults.update(self._block("wizard"))
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
        raw = load_yaml_mapping(path)
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

        Relative paths resolve under ``base_dir`` (defaults to the current
        working directory).
        """
        base = Path(base_dir or os.getcwd()).resolve()
        return cls(yaml_path=base / _YAML_FILENAME, base_dir=base, raw={})
