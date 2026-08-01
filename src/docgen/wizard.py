"""Production wizard — local Flask web GUI for narration bootstrapping and per-segment review."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

STATE_FILENAME = ".docgen-state.json"


# ---------------------------------------------------------------------------
# File tree scanner
# ---------------------------------------------------------------------------

def _load_gitignore_patterns(repo_root: Path) -> list[str]:
    """Read .gitignore and return glob patterns."""
    gi = repo_root / ".gitignore"
    if not gi.exists():
        return []
    patterns: list[str] = []
    for line in gi.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(rel_path: str, gitignore: list[str], extra_excludes: list[str]) -> bool:
    for pat in gitignore + extra_excludes:
        candidates = [pat]
        if pat.startswith("**/"):
            candidates.append(pat[3:])
        for p in candidates:
            if fnmatch.fnmatch(rel_path, p):
                return True
        parts = rel_path.split("/")
        for i in range(len(parts)):
            partial = "/".join(parts[: i + 1])
            stripped = pat.rstrip("/").removeprefix("**/")
            if fnmatch.fnmatch(partial, pat.rstrip("/")) or fnmatch.fnmatch(partial, stripped):
                return True
    return False


# Default extensions the wizard can offer as narration / scene focus context.
DEFAULT_SCAN_EXTENSIONS = (
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
)


def scan_md_files(repo_root: Path, exclude_patterns: list[str] | None = None) -> list[dict]:
    """Walk repo_root and return a flat list of .md file info dicts."""
    return scan_repo_files(repo_root, exclude_patterns=exclude_patterns, extensions=(".md",))


def scan_repo_files(
    repo_root: Path,
    exclude_patterns: list[str] | None = None,
    extensions: tuple[str, ...] | list[str] | None = None,
) -> list[dict]:
    """Walk ``repo_root`` and return file info dicts for allowed extensions.

    Paths are repo-root-relative. Used by the wizard so maintainers can pick
    focus files (not only Markdown) for ``context.paths``.
    """
    from docgen.path_filters import is_under_archive_dir

    gitignore = _load_gitignore_patterns(repo_root)
    excludes = exclude_patterns or []
    exts = tuple(extensions) if extensions is not None else DEFAULT_SCAN_EXTENSIONS
    exts_norm = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    results: list[dict] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts_norm:
            continue
        rel = str(path.relative_to(repo_root))
        if rel.startswith(".git/"):
            continue
        if is_under_archive_dir(rel):
            continue
        if _is_ignored(rel, gitignore, excludes):
            continue
        snippet = ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:4]
            snippet = "\n".join(lines)
        except OSError:
            pass
        results.append({"path": rel, "snippet": snippet, "ext": path.suffix.lower()})
    return results


def build_file_tree(files: list[dict]) -> list[dict]:
    """Convert flat file list into a nested tree structure for the frontend."""
    tree: dict[str, Any] = {}
    for f in files:
        parts = f["path"].split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {"__children": {}})["__children"]
        node[parts[-1]] = {"__file": True, "path": f["path"], "snippet": f["snippet"]}

    def _to_list(d: dict, prefix: str = "") -> list[dict]:
        items: list[dict] = []
        for name, val in sorted(d.items()):
            full = f"{prefix}/{name}" if prefix else name
            if isinstance(val, dict) and "__file" in val:
                items.append({
                    "type": "file",
                    "name": name,
                    "path": val["path"],
                    "snippet": val["snippet"],
                })
            elif isinstance(val, dict):
                children_dict = val.get("__children", val)
                items.append({
                    "type": "dir",
                    "name": name,
                    "path": full,
                    "children": _to_list(children_dict, full),
                })
        return items

    return _to_list(tree)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _state_path(base_dir: Path) -> Path:
    return base_dir / STATE_FILENAME


def load_state(base_dir: Path) -> dict[str, Any]:
    p = _state_path(base_dir)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"segments": {}}


def save_state(base_dir: Path, state: dict[str, Any]) -> None:
    p = _state_path(base_dir)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM narration generation
# ---------------------------------------------------------------------------

def generate_narration_via_llm(
    source_texts: list[str],
    guidance: str,
    system_prompt: str,
    model: str,
    segment_name: str,
    revision_notes: str = "",
    *,
    temperature: float = 0.7,
    topic_label: str | None = None,
    current_narration: str = "",
    mode: str = "generate",
) -> str:
    """Call OpenAI to generate or revise a narration draft.

    ``guidance`` is **caller-supplied** (e.g. project-owner hints from ``docgen.yaml``), not
    text returned from a prior model call. ``topic_label`` is a human-facing focus
    line (e.g. ``Config.narration_topic_label``); when present it is what the model
    sees in the user prompt so spoken output never echoes file stems / segment ids.

    ``mode="revise"`` (or auto when ``current_narration`` + ``revision_notes`` are
    both non-empty) edits the existing script in place: address feedback, keep
    structure/phrasing that still work, do not rewrite from scratch unless needed.
    """
    import openai

    focus = (topic_label or "").strip() or _strip_segment_prefix(segment_name)
    notes = (revision_notes or "").strip()
    current = (current_narration or "").strip()
    mode_norm = str(mode or "generate").strip().lower()
    if mode_norm not in ("generate", "revise"):
        mode_norm = "generate"
    # Auto-revise when the caller supplied both an existing script and notes.
    if mode_norm == "generate" and current and notes:
        mode_norm = "revise"

    if mode_norm == "revise":
        if not current:
            raise ValueError("revise mode requires current_narration text")
        if not notes:
            raise ValueError("revise mode requires revision_notes")
        user_parts = [
            f"Revise the narration script focused on: {focus}.",
            "Edit the CURRENT NARRATION in place: address the revision notes, "
            "preserve structure and phrasing that still work, and do not rewrite "
            "from scratch unless the notes require it.",
            "Do not mention segment numbers, file stems, ordinals, or any 'segment NN' phrasing.",
            "Return only the revised narration markdown (no preamble).",
            "",
            "--- CURRENT NARRATION ---",
            current,
            "--- END CURRENT NARRATION ---",
        ]
        if source_texts:
            user_parts += [
                "",
                "--- SOURCE DOCUMENTATION (reference only) ---",
                *source_texts,
                "--- END SOURCE DOCUMENTATION ---",
            ]
        if guidance:
            user_parts += [
                "",
                "--- PROJECT OWNER HINTS ---",
                guidance,
                "--- END PROJECT OWNER HINTS ---",
            ]
        user_parts += [
            "",
            "--- REVISION NOTES (address these) ---",
            notes,
            "--- END REVISION NOTES ---",
        ]
        sys_prompt = (
            system_prompt
            + "\nYou are revising an existing narration script. Prefer minimal edits "
            "that satisfy the revision notes over a full rewrite."
        )
    else:
        user_parts = [
            f"Write a narration script focused on: {focus}.",
            "Do not mention segment numbers, file stems, ordinals, or any 'segment NN' phrasing.",
            "",
            "--- SOURCE DOCUMENTATION ---",
            *source_texts,
            "--- END SOURCE DOCUMENTATION ---",
        ]
        if guidance:
            user_parts += [
                "",
                "--- PROJECT OWNER HINTS ---",
                guidance,
                "--- END PROJECT OWNER HINTS ---",
            ]
        if notes:
            user_parts += [
                "",
                "--- REVISION NOTES (address these) ---",
                notes,
                "--- END REVISION NOTES ---",
            ]
        sys_prompt = system_prompt

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
        temperature=float(temperature),
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def _strip_segment_prefix(segment_name: str) -> str:
    """Strip a leading ``NN-`` / ``NN_`` from a file stem so prompts don't see ids."""
    import re as _re

    cleaned = _re.sub(r"^\d+[-_]", "", segment_name).strip("-_ ").strip()
    return cleaned or segment_name


def _find_asset(directory: Path, seg_name: str, seg_id: str, ext: str) -> Path | None:
    """Find an asset file by segment name, then segment ID prefix, then glob."""
    if not directory.exists():
        return None
    exact = directory / f"{seg_name}{ext}"
    if exact.exists():
        return exact
    exact_id = directory / f"{seg_id}{ext}"
    if exact_id.exists():
        return exact_id
    for f in directory.glob(f"{seg_id}-*{ext}"):
        return f
    for f in directory.glob(f"{seg_id}*{ext}"):
        return f
    return None


def create_app(config: Any | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["DOCGEN"] = config

    def _cfg():
        return app.config["DOCGEN"]

    # -- Pages -----------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("wizard.html")

    # -- API: scan files -------------------------------------------------------

    @app.route("/api/scan")
    def api_scan():
        cfg = _cfg()
        root = cfg.repo_root if cfg else Path.cwd()
        wiz = cfg.wizard_config if cfg else {}
        excludes = wiz.get("exclude_patterns", [])
        raw_ext = request.args.get("extensions")
        if raw_ext:
            exts = tuple(e.strip() for e in raw_ext.split(",") if e.strip())
        else:
            cfg_ext = wiz.get("scan_extensions")
            if isinstance(cfg_ext, list) and cfg_ext:
                exts = tuple(str(e) for e in cfg_ext)
            else:
                exts = DEFAULT_SCAN_EXTENSIONS
        files = scan_repo_files(root, exclude_patterns=excludes, extensions=exts)
        tree = build_file_tree(files)
        return jsonify({
            "tree": tree,
            "files": files,
            "repo_root": str(root),
            "extensions": list(exts),
        })

    # -- API: read file content ------------------------------------------------

    @app.route("/api/file")
    def api_file():
        cfg = _cfg()
        root = cfg.repo_root if cfg else Path.cwd()
        rel = request.args.get("path", "")
        fpath = root / rel
        if not fpath.exists() or not str(fpath.resolve()).startswith(str(root.resolve())):
            return jsonify({"error": "not found"}), 404
        return jsonify({"content": fpath.read_text(encoding="utf-8", errors="replace")})

    # -- API: generate narration -----------------------------------------------

    @app.route("/api/generate-narration", methods=["POST"])
    def api_generate_narration():
        cfg = _cfg()
        data = request.json or {}
        source_paths: list[str] = list(data.get("source_paths") or [])
        guidance: str = data.get("guidance", "")
        segment_name: str = data.get("segment_name", "untitled")
        revision_notes: str = data.get("revision_notes", "")
        current_narration: str = data.get("current_narration", "") or ""
        mode: str = data.get("mode", "generate") or "generate"
        topic_label: str | None = data.get("topic_label") or None
        seg_id_hint: str | None = data.get("segment_id")
        if topic_label is None and cfg is not None and seg_id_hint:
            try:
                topic_label = cfg.narration_topic_label(seg_id_hint)
            except Exception:
                topic_label = None

        root = cfg.repo_root if cfg else Path.cwd()
        wiz = cfg.wizard_config if cfg else {}

        # When the UI sends no explicit paths, reuse durable focus files from
        # hint wiring / narration_from_source.context.paths.
        if not source_paths and cfg is not None:
            sid = seg_id_hint or (
                segment_name[:2] if len(segment_name) >= 2 and segment_name[:2].isdigit() else None
            )
            if sid:
                from docgen.narrate_from_source import merged_narration_from_source_settings
                from docgen.yaml_generate import read_hint_focus_paths

                hint_paths = read_hint_focus_paths(cfg.hints_dir, sid)
                settings = merged_narration_from_source_settings(cfg, sid)
                seen: list[str] = []
                for p in hint_paths + list(settings.context_paths):
                    if p not in seen:
                        seen.append(p)
                source_paths = seen

        source_texts = []
        for rel in source_paths:
            fpath = root / rel
            if fpath.exists() and fpath.is_file():
                source_texts.append(
                    f"## File: {rel}\n{fpath.read_text(encoding='utf-8', errors='replace')}"
                )

        try:
            narration = generate_narration_via_llm(
                source_texts=source_texts,
                guidance=guidance,
                system_prompt=wiz.get("system_prompt", "Write narration for a demo video."),
                model=wiz.get("llm_model", "gpt-4o"),
                segment_name=segment_name,
                revision_notes=revision_notes,
                topic_label=topic_label,
                current_narration=current_narration,
                mode=mode,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        narration_dir = cfg.narration_dir if cfg else Path.cwd() / "narration"
        narration_dir.mkdir(parents=True, exist_ok=True)
        out = narration_dir / f"{segment_name}.md"
        out.write_text(narration + "\n", encoding="utf-8")

        effective_mode = str(mode or "generate").strip().lower()
        if effective_mode not in ("generate", "revise"):
            effective_mode = "generate"
        if effective_mode == "generate" and current_narration.strip() and revision_notes.strip():
            effective_mode = "revise"

        return jsonify({
            "narration": narration,
            "path": str(out),
            "source_paths": source_paths,
            "mode": effective_mode,
        })

    # -- API: segment state ----------------------------------------------------

    @app.route("/api/state")
    def api_get_state():
        cfg = _cfg()
        base = cfg.base_dir if cfg else Path.cwd()
        return jsonify(load_state(base))

    @app.route("/api/state", methods=["POST"])
    def api_set_state():
        cfg = _cfg()
        base = cfg.base_dir if cfg else Path.cwd()
        state = request.json or {}
        save_state(base, state)
        return jsonify({"ok": True})

    # -- API: list segments with asset info ------------------------------------

    @app.route("/api/segments")
    def api_segments():
        cfg = _cfg()
        if not cfg:
            return jsonify({"segments": []})
        from docgen.yaml_generate import read_hint_focus_paths

        base = cfg.base_dir
        state = load_state(base)
        result = []
        for seg_id in cfg.segments_all:
            seg_name = cfg.resolve_segment_name(seg_id)

            narr_found = _find_asset(cfg.narration_dir, seg_name, seg_id, ".md")
            audio_found = _find_asset(cfg.audio_dir, seg_name, seg_id, ".mp3")
            rec_found = _find_asset(cfg.recordings_dir, seg_name, seg_id, ".mp4")

            seg_state = state.get("segments", {}).get(seg_id, {})
            focus_paths = read_hint_focus_paths(cfg.hints_dir, seg_id)
            if not focus_paths:
                from docgen.narrate_from_source import merged_narration_from_source_settings
                focus_paths = list(
                    merged_narration_from_source_settings(cfg, seg_id).context_paths
                )
            from docgen.asset_graph import segment_asset_report

            assets = segment_asset_report(cfg, seg_id)
            result.append({
                "id": seg_id,
                "name": seg_name,
                "status": seg_state.get("status", "draft"),
                "revision_notes": seg_state.get("revision_notes", ""),
                "has_narration": narr_found is not None,
                "has_audio": audio_found is not None,
                "has_recording": rec_found is not None,
                "narration_path": str(narr_found.relative_to(base)) if narr_found else None,
                "audio_path": str(audio_found.relative_to(base)) if audio_found else None,
                "recording_path": str(rec_found.relative_to(base)) if rec_found else None,
                "visual_map": cfg.visual_map.get(seg_id, {}),
                "focus_paths": focus_paths,
                "assets": assets,
            })
        return jsonify({"segments": result})

    @app.route("/api/segments/<segment_id>/assets")
    def api_segment_assets(segment_id: str):
        """Return per-step freshness for rebuild-from-here UI."""
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        from docgen.asset_graph import segment_asset_report

        return jsonify(segment_asset_report(cfg, segment_id))

    @app.route("/api/segments/<segment_id>/focus")
    def api_get_focus(segment_id: str):
        """Return durable focus file paths for a segment (hint wiring / config)."""
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        from docgen.yaml_generate import find_hint_path_for_segment, read_hint_focus_paths

        paths = read_hint_focus_paths(cfg.hints_dir, segment_id)
        hint = find_hint_path_for_segment(cfg.hints_dir, segment_id)
        return jsonify({
            "segment_id": segment_id,
            "paths": paths,
            "hint_path": str(hint.relative_to(cfg.base_dir)) if hint else None,
        })

    @app.route("/api/segments/<segment_id>/focus", methods=["PUT"])
    def api_put_focus(segment_id: str):
        """Persist focus files into hint front matter and re-run yaml-generate merge.

        Body: ``{"paths": ["rel/path.py", ...], "also_manim": true, "yaml_generate": true}``
        """
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        data = request.json or {}
        paths = data.get("paths")
        if not isinstance(paths, list):
            return jsonify({"error": "paths must be a list of repo-root-relative strings"}), 400
        also_manim = data.get("also_manim", True)
        do_yaml = data.get("yaml_generate", True)

        root = cfg.repo_root.resolve()
        clean: list[str] = []
        for raw in paths:
            rel = str(raw).strip().replace("\\", "/")
            if not rel or rel.startswith("/") or ".." in rel.split("/"):
                return jsonify({"error": f"invalid path: {raw!r}"}), 400
            fpath = (root / rel).resolve()
            try:
                fpath.relative_to(root)
            except ValueError:
                return jsonify({"error": f"path escapes repo_root: {rel}"}), 400
            if not fpath.is_file():
                return jsonify({"error": f"file not found: {rel}"}), 400
            clean.append(rel)

        from docgen.yaml_generate import ensure_segment_hint_with_focus

        stem = cfg.resolve_segment_name(segment_id)
        try:
            hint_path, written = ensure_segment_hint_with_focus(
                cfg.hints_dir,
                segment_id,
                stem=stem,
                paths=clean,
                also_manim=bool(also_manim),
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

        yaml_changes: list[str] = []
        if do_yaml:
            try:
                import copy

                import yaml as _yaml

                from docgen.yaml_generate import default_header, merge_defaults, write_docgen_yaml

                raw = _yaml.safe_load(cfg.yaml_path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    raw = {}
                # Work on a deep copy so a failed merge never leaves half-mutated state
                # in memory before we rewrite the file.
                working = copy.deepcopy(raw)
                yaml_changes.extend(merge_defaults(working, cfg))
                write_docgen_yaml(cfg.yaml_path, working, header=default_header(cfg.yaml_path))
                from docgen.config import Config
                app.config["DOCGEN"] = Config.from_yaml(cfg.yaml_path)
            except Exception as exc:
                return jsonify({
                    "error": f"hints updated but yaml-generate failed: {exc}",
                    "hint_path": str(hint_path.relative_to(cfg.base_dir)),
                    "paths": written,
                }), 500

        return jsonify({
            "ok": True,
            "segment_id": segment_id,
            "paths": written,
            "hint_path": str(hint_path.relative_to(cfg.base_dir)),
            "yaml_changes": yaml_changes,
        })

    # -- API: read/write narration text ----------------------------------------

    @app.route("/api/narration/<segment_id>")
    def api_get_narration(segment_id: str):
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        seg_name = cfg.resolve_segment_name(segment_id)
        found = _find_asset(cfg.narration_dir, seg_name, segment_id, ".md")
        if found:
            return jsonify({
                "text": found.read_text(encoding="utf-8"),
                "path": str(found.relative_to(cfg.base_dir)),
            })
        return jsonify({"text": "", "path": None})

    @app.route("/api/narration/<segment_id>", methods=["PUT"])
    def api_put_narration(segment_id: str):
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        data = request.json or {}
        text = data.get("text", "")
        seg_name = cfg.resolve_segment_name(segment_id)
        found = _find_asset(cfg.narration_dir, seg_name, segment_id, ".md")
        target = found or (cfg.narration_dir / f"{seg_name}.md")
        cfg.narration_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return jsonify({"ok": True, "path": str(target.relative_to(cfg.base_dir))})

    # -- API: run pipeline steps for a single segment --------------------------

    def _run_segment_step(cfg: Any, step: str, segment_id: str) -> dict[str, Any]:
        """Execute one pipeline step; raise on failure. Returns a result dict."""
        if step == "tts":
            from docgen.tts import TTSGenerator

            TTSGenerator(cfg).generate(segment=segment_id)
            return {"ok": True, "step": "tts", "segment": segment_id}

        if step == "timestamps":
            import json as _json

            from docgen.timestamps import TimestampExtractor

            seg_name = cfg.resolve_segment_name(segment_id)
            mp3 = _find_asset(cfg.audio_dir, seg_name, segment_id, ".mp3")
            if mp3 is None:
                raise RuntimeError(
                    f"no audio for segment {segment_id}; run TTS first"
                )
            ts = TimestampExtractor(cfg)
            engine = ts.resolve_engine(None)
            block = (
                ts.extract(mp3) if engine == "whisper" else ts.extract_local(mp3)
            )
            out = cfg.animations_dir / "timing.json"
            timing: dict = {}
            if out.is_file():
                try:
                    timing = _json.loads(out.read_text(encoding="utf-8"))
                except _json.JSONDecodeError:
                    timing = {}
            if not isinstance(timing, dict):
                timing = {}
            timing[mp3.stem] = block
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                _json.dumps(timing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            from docgen.manim_scene_support import sync_audio_tail_waits_in_scenes

            sync_audio_tail_waits_in_scenes(cfg)
            return {"ok": True, "step": "timestamps", "segment": segment_id}

        if step == "scene-retime":
            from docgen.scene_retime import list_scene_spec_paths, retime_compile_spec

            paths = list_scene_spec_paths(cfg, segment_id=segment_id)
            if not paths:
                raise RuntimeError(
                    f"no scene spec for segment {segment_id}; "
                    "run scene-spec (LLM) first or add animations/specs/*.scene.yaml"
                )
            results = [retime_compile_spec(cfg, p) for p in paths]
            return {
                "ok": True,
                "step": "scene-retime",
                "segment": segment_id,
                "compiled": [str(r.get("path")) for r in results],
            }

        if step == "scene-spec":
            from docgen.scene_spec_generate import (
                generate_scene_spec,
                inject_class_block_into_scenes_py,
                linted_class_block_from_spec,
            )

            res = generate_scene_spec(
                cfg, segment_id, extra_paths=[], extra_hints=[]
            )
            specs_dir = cfg.animations_dir / "specs"
            specs_dir.mkdir(parents=True, exist_ok=True)
            wpath = specs_dir / f"{res.seg_name}.scene.yaml"
            wpath.write_text(res.yaml_text, encoding="utf-8")
            class_block, merged = linted_class_block_from_spec(
                cfg, res.spec, timing_key=res.seg_name
            )
            inject_class_block_into_scenes_py(
                cfg,
                seg_id=merged["segment_id"],
                class_name=merged["class_name"],
                class_block=class_block,
            )
            return {"ok": True, "step": "scene-spec", "segment": segment_id}

        if step == "manim":
            from docgen.manim_runner import ManimRunner

            runner = ManimRunner(cfg)
            vmap = cfg.visual_map.get(segment_id, {})
            scene = vmap.get("scene")
            if scene:
                runner.render(scene=scene)
            return {"ok": True, "step": "manim", "segment": segment_id}

        if step == "compose":
            from docgen.compose import Composer

            Composer(cfg).compose_segments([segment_id])
            return {"ok": True, "step": "compose", "segment": segment_id}

        if step == "validate":
            from docgen.validate import Validator

            report = Validator(cfg).validate_segment(segment_id)
            return {
                "ok": True,
                "step": "validate",
                "segment": segment_id,
                "report": report,
            }

        raise ValueError(f"Unknown step: {step}")

    @app.route("/api/run/<step>/<segment_id>", methods=["POST"])
    def api_run_step(step: str, segment_id: str):
        """Run a single pipeline step for one segment. Returns result or error."""
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        try:
            return jsonify(_run_segment_step(cfg, step, segment_id))
        except ValueError as exc:
            return jsonify({"error": str(exc), "step": step, "segment": segment_id}), 400
        except Exception as exc:
            return jsonify({"error": str(exc), "step": step, "segment": segment_id}), 500

    @app.route("/api/run-from/<step>/<segment_id>", methods=["POST"])
    def api_run_from(step: str, segment_id: str):
        """Run ``step`` and all downstream cascade steps (rebuild-from-here).

        Body (optional): ``{"llm_scene_spec": false}`` — when true, the cascade
        uses LLM ``scene-spec`` instead of offline ``scene-retime``.
        """
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        data = request.json or {}
        llm_scene = bool(data.get("llm_scene_spec", False))
        from docgen.asset_graph import cascade_steps

        try:
            steps = cascade_steps(step, llm_scene_spec=llm_scene)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        ran: list[dict[str, Any]] = []
        for s in steps:
            try:
                result = _run_segment_step(cfg, s, segment_id)
            except Exception as exc:
                return jsonify({
                    "ok": False,
                    "error": str(exc),
                    "failed_step": s,
                    "ran": ran,
                    "planned": steps,
                    "segment": segment_id,
                }), 500
            ran.append({"step": s, "ok": True})
            # Attach validate report on the final payload if present.
            if s == "validate" and "report" in result:
                ran[-1]["report"] = result["report"]
        return jsonify({
            "ok": True,
            "segment": segment_id,
            "from_step": step,
            "planned": steps,
            "ran": ran,
        })

    # -- API: serve media files ------------------------------------------------

    @app.route("/media/<path:rel_path>")
    def serve_media(rel_path: str):
        """Serve audio/video files from the demos directory."""
        from flask import send_from_directory
        cfg = _cfg()
        base = cfg.base_dir if cfg else Path.cwd()
        return send_from_directory(str(base), rel_path)

    return app
