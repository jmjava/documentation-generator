"""Production wizard — local Flask web GUI for narration bootstrapping and per-segment review."""

from __future__ import annotations

import fnmatch
import json
import subprocess
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
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, f"**/{pat}"):
            return True
        parts = rel_path.split("/")
        for i in range(len(parts)):
            partial = "/".join(parts[: i + 1])
            if fnmatch.fnmatch(partial, pat.rstrip("/")):
                return True
    return False


def scan_md_files(repo_root: Path, exclude_patterns: list[str] | None = None) -> list[dict]:
    """Walk repo_root and return a flat list of .md file info dicts."""
    gitignore = _load_gitignore_patterns(repo_root)
    excludes = exclude_patterns or []
    results: list[dict] = []
    for md in sorted(repo_root.rglob("*.md")):
        rel = str(md.relative_to(repo_root))
        if rel.startswith(".git/"):
            continue
        if _is_ignored(rel, gitignore, excludes):
            continue
        snippet = ""
        try:
            lines = md.read_text(encoding="utf-8", errors="replace").splitlines()[:4]
            snippet = "\n".join(lines)
        except OSError:
            pass
        results.append({"path": rel, "snippet": snippet})
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
) -> str:
    """Call OpenAI to generate a narration draft from source docs + guidance."""
    import openai

    user_parts = [
        f"Generate a narration script for demo video segment '{segment_name}'.",
        "",
        "--- SOURCE DOCUMENTATION ---",
        *source_texts,
        "--- END SOURCE DOCUMENTATION ---",
    ]
    if guidance:
        user_parts += ["", "--- USER GUIDANCE ---", guidance, "--- END USER GUIDANCE ---"]
    if revision_notes:
        user_parts += [
            "",
            "--- REVISION NOTES (address these) ---",
            revision_notes,
            "--- END REVISION NOTES ---",
        ]

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

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
        excludes = cfg.wizard_config.get("exclude_patterns", []) if cfg else []
        files = scan_md_files(root, excludes)
        tree = build_file_tree(files)
        return jsonify({"tree": tree, "files": files, "repo_root": str(root)})

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
        source_paths: list[str] = data.get("source_paths", [])
        guidance: str = data.get("guidance", "")
        segment_name: str = data.get("segment_name", "untitled")
        revision_notes: str = data.get("revision_notes", "")

        root = cfg.repo_root if cfg else Path.cwd()
        wiz = cfg.wizard_config if cfg else {}

        source_texts = []
        for rel in source_paths:
            fpath = root / rel
            if fpath.exists():
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
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        narration_dir = cfg.narration_dir if cfg else Path.cwd() / "narration"
        narration_dir.mkdir(parents=True, exist_ok=True)
        out = narration_dir / f"{segment_name}.md"
        out.write_text(narration + "\n", encoding="utf-8")

        return jsonify({"narration": narration, "path": str(out)})

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
        base = cfg.base_dir
        state = load_state(base)
        result = []
        for seg_id in cfg.segments_all:
            narration_file = cfg.narration_dir / f"{seg_id}.md" if cfg.narration_dir.exists() else None
            narration_path = cfg.narration_dir / f"{seg_id}.md"
            audio_path = cfg.audio_dir / f"{seg_id}.mp3"
            rec_path = cfg.recordings_dir / f"{seg_id}.mp4"

            # Try to find the recording with any name prefix
            rec_found = None
            if cfg.recordings_dir.exists():
                for mp4 in cfg.recordings_dir.glob(f"{seg_id}*.mp4"):
                    rec_found = mp4
                    break
                if not rec_found:
                    for mp4 in cfg.recordings_dir.glob(f"*{seg_id}*.mp4"):
                        rec_found = mp4
                        break

            seg_state = state.get("segments", {}).get(seg_id, {})
            result.append({
                "id": seg_id,
                "status": seg_state.get("status", "draft"),
                "revision_notes": seg_state.get("revision_notes", ""),
                "has_narration": narration_path.exists(),
                "has_audio": audio_path.exists() or bool(
                    list(cfg.audio_dir.glob(f"*{seg_id}*.mp3")) if cfg.audio_dir.exists() else []
                ),
                "has_recording": rec_found is not None,
                "narration_path": str(narration_path.relative_to(base)) if narration_path.exists() else None,
                "audio_path": str(next(cfg.audio_dir.glob(f"*{seg_id}*.mp3")).relative_to(base))
                    if cfg.audio_dir.exists() and list(cfg.audio_dir.glob(f"*{seg_id}*.mp3"))
                    else None,
                "recording_path": str(rec_found.relative_to(base)) if rec_found else None,
                "visual_map": cfg.visual_map.get(seg_id, {}),
            })
        return jsonify({"segments": result})

    # -- API: read/write narration text ----------------------------------------

    @app.route("/api/narration/<segment_id>")
    def api_get_narration(segment_id: str):
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        # Try exact match first, then glob
        candidates = [
            cfg.narration_dir / f"{segment_id}.md",
        ]
        if cfg.narration_dir.exists():
            candidates.extend(cfg.narration_dir.glob(f"*{segment_id}*.md"))
        for p in candidates:
            if p.exists():
                return jsonify({
                    "text": p.read_text(encoding="utf-8"),
                    "path": str(p.relative_to(cfg.base_dir)),
                })
        return jsonify({"text": "", "path": None})

    @app.route("/api/narration/<segment_id>", methods=["PUT"])
    def api_put_narration(segment_id: str):
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400
        data = request.json or {}
        text = data.get("text", "")
        # Find or create narration file
        target = cfg.narration_dir / f"{segment_id}.md"
        if cfg.narration_dir.exists():
            for existing in cfg.narration_dir.glob(f"*{segment_id}*.md"):
                target = existing
                break
        cfg.narration_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return jsonify({"ok": True, "path": str(target.relative_to(cfg.base_dir))})

    # -- API: run pipeline steps for a single segment --------------------------

    @app.route("/api/run/<step>/<segment_id>", methods=["POST"])
    def api_run_step(step: str, segment_id: str):
        """Run a single pipeline step for one segment. Returns result or error."""
        cfg = _cfg()
        if not cfg:
            return jsonify({"error": "no config"}), 400

        try:
            if step == "tts":
                from docgen.tts import TTSGenerator
                gen = TTSGenerator(cfg)
                gen.generate(segment=segment_id)
                return jsonify({"ok": True, "step": "tts", "segment": segment_id})

            elif step == "manim":
                from docgen.manim_runner import ManimRunner
                runner = ManimRunner(cfg)
                vmap = cfg.visual_map.get(segment_id, {})
                scene = vmap.get("scene")
                if scene:
                    runner.render(scene=scene)
                return jsonify({"ok": True, "step": "manim", "segment": segment_id})

            elif step == "vhs":
                from docgen.vhs import VHSRunner
                runner = VHSRunner(cfg)
                vmap = cfg.visual_map.get(segment_id, {})
                tape = vmap.get("tape")
                if tape:
                    runner.render(tape=tape, strict=False)
                return jsonify({"ok": True, "step": "vhs", "segment": segment_id})

            elif step == "compose":
                from docgen.compose import Composer
                comp = Composer(cfg)
                comp.compose_segments([segment_id])
                return jsonify({"ok": True, "step": "compose", "segment": segment_id})

            elif step == "validate":
                from docgen.validate import Validator
                v = Validator(cfg)
                report = v.validate_segment(segment_id)
                return jsonify({"ok": True, "step": "validate", "segment": segment_id, "report": report})

            else:
                return jsonify({"error": f"Unknown step: {step}"}), 400

        except Exception as exc:
            return jsonify({"error": str(exc), "step": step, "segment": segment_id}), 500

    # -- API: serve media files ------------------------------------------------

    @app.route("/media/<path:rel_path>")
    def serve_media(rel_path: str):
        """Serve audio/video files from the demos directory."""
        from flask import send_from_directory
        cfg = _cfg()
        base = cfg.base_dir if cfg else Path.cwd()
        return send_from_directory(str(base), rel_path)

    return app
