"""Interactive project scaffolding wizard for docgen.

`docgen init` writes structure only (directories, wrapper scripts, an empty
``visual_map`` in ``docgen.yaml``) and **never** hardcodes segment numbers,
fixture paths, or visual-tool wiring. Specific bundles (e.g. the dogfood
``docs/demos`` tree) come from running ``docgen yaml-generate`` against the
files that already exist on disk, not from baked-in presets.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import click
import yaml


@dataclass
class InitPlan:
    """Collected answers from the init wizard, used to generate files."""

    project_name: str = ""
    demo_dir: Path = field(default_factory=lambda: Path.cwd())
    repo_root: Path = field(default_factory=lambda: Path.cwd())
    segments: list[dict[str, str]] = field(default_factory=list)
    tts_voice: str = "coral"
    tts_model: str = "gpt-4o-mini-tts"
    install_pre_push: bool = False
    env_file_rel: str = ""
    existing_narrations: list[Path] = field(default_factory=list)
    discover_roots: list[str] = field(default_factory=lambda: ["."])


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge ``overlay`` into ``copy(base)`` (dict values only)."""
    out = dict(base)
    for key, val in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


_PLAYWRIGHT_PKG_DEPS: tuple[str, ...] = ("@playwright/test", "playwright", "playwright-core")
_PLAYWRIGHT_CONFIG_NAMES: tuple[str, ...] = (
    "playwright.config.js",
    "playwright.config.ts",
    "playwright.config.mjs",
    "playwright.config.cjs",
)
_DETECT_SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules",
    ".git",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
    "target",
    "archive",
})


def _package_json_has_playwright(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(section)
        if isinstance(deps, dict) and any(name in deps for name in _PLAYWRIGHT_PKG_DEPS):
            return True
    return False


def detect_playwright_project_dirs(repo_root: Path, *, max_depth: int = 6) -> list[Path]:
    """Return directories under ``repo_root`` that look like Playwright projects.

    Detection signals (no path or fixture name is hardcoded):

    - A ``package.json`` listing ``@playwright/test`` / ``playwright`` /
      ``playwright-core`` in any deps section.
    - A ``playwright.config.{js,ts,mjs,cjs}`` file.

    Walks up to ``max_depth`` levels deep, skipping common build / vendor dirs.
    Results are deduplicated and sorted (shallowest, then alphabetical).
    """
    repo_root = repo_root.resolve()
    if not repo_root.is_dir():
        return []
    found: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(repo_root):
        d = Path(dirpath)
        try:
            depth = len(d.resolve().relative_to(repo_root).parts)
        except ValueError:
            dirnames[:] = []
            continue
        if depth > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(n for n in dirnames if n not in _DETECT_SKIP_DIRS and not n.startswith("."))
        names = set(filenames)
        if names & set(_PLAYWRIGHT_CONFIG_NAMES):
            found.add(d)
            continue
        if "package.json" in names and _package_json_has_playwright(d / "package.json"):
            found.add(d)
    return sorted(found, key=lambda p: (len(p.relative_to(repo_root).parts), str(p)))


def discover_default_discover_roots(repo_root: Path, _demo_dir: Path) -> list[str]:
    """Default ``discover_tests.roots`` based on actual Playwright signals.

    Always starts with ``.`` (repo root — same base as :meth:`Config.discover_tests_scan_roots`).
    For each detected Playwright project (see :func:`detect_playwright_project_dirs`), append
    its path **relative to** ``repo_root``. No fixture name is hardcoded.

    ``_demo_dir`` is kept for call-site compatibility; it is not used (roots must match YAML
    semantics where ``discover_tests.roots`` entries join ``repo_root``, not the bundle dir).
    """
    rr = repo_root.resolve()
    roots: list[str] = ["."]
    for proj in detect_playwright_project_dirs(repo_root):
        try:
            rel = os.path.relpath(proj, rr)
        except ValueError:
            continue
        rel = rel.replace(os.sep, "/")
        if rel and rel not in roots:
            roots.append(rel)
    return roots


def read_segments_file(path: Path) -> list[dict[str, str]]:
    """Parse a plain-text segments file: one stem per line.

    Blank lines and ``#`` comment lines are ignored. Each remaining line is a
    segment ``name`` (e.g. ``01-overview``). The segment ``id`` is the leading
    two-digit prefix when present, otherwise a 1-based zero-padded ordinal.
    Duplicate names are deduplicated, preserving first occurrence.
    """
    raw = path.read_text(encoding="utf-8")
    segments: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        match = re.match(r"^(\d{2})", stripped)
        seg_id = match.group(1) if match else str(len(segments) + 1).zfill(2)
        segments.append({"id": seg_id, "name": stripped})
    return segments


def build_defaults_plan(
    target_dir: Path | None,
    *,
    discover_roots: tuple[str, ...] = (),
    segments_file: Path | None = None,
) -> InitPlan:
    """Non-interactive plan: git root, demo dir, segments from a segments file,
    existing narration filenames, or a single starter (in that order)."""
    plan = InitPlan()
    git_root = detect_git_root(target_dir)
    plan.repo_root = git_root.resolve() if git_root else (target_dir or Path.cwd()).resolve()
    if target_dir is not None:
        plan.demo_dir = Path(target_dir).resolve()
    else:
        plan.demo_dir = (plan.repo_root / "docs" / "demos").resolve()
    plan.project_name = plan.repo_root.name

    if plan.repo_root.joinpath(".env").is_file():
        plan.env_file_rel = os.path.relpath(plan.repo_root / ".env", plan.demo_dir)

    if discover_roots:
        plan.discover_roots = list(discover_roots)
    else:
        plan.discover_roots = discover_default_discover_roots(plan.repo_root, plan.demo_dir)

    plan.existing_narrations = scan_narrations(plan.demo_dir)
    if segments_file is not None:
        plan.segments = read_segments_file(segments_file)
        if not plan.segments:
            plan.segments = [{"id": "01", "name": "01-intro"}]
    elif plan.existing_narrations:
        plan.segments = infer_segments_from_narrations(plan.existing_narrations)
    else:
        plan.segments = [{"id": "01", "name": "01-intro"}]

    plan.install_pre_push = False
    return plan


def detect_git_root(start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    while cur != cur.parent:
        if (cur / ".git").exists():
            return cur
        cur = cur.parent
    return None


def scan_narrations(demo_dir: Path) -> list[Path]:
    narr_dir = demo_dir / "narration"
    if not narr_dir.exists():
        return []
    return sorted(
        f for f in narr_dir.glob("*.md")
        if f.name.lower() != "readme.md"
    )


def infer_segments_from_narrations(files: list[Path]) -> list[dict[str, str]]:
    segments = []
    for f in files:
        stem = f.stem
        match = re.match(r"^(\d{2})", stem)
        seg_id = match.group(1) if match else str(len(segments) + 1).zfill(2)
        segments.append({"id": seg_id, "name": stem})
    return segments


def scan_existing_assets(demo_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for subdir, ext in [
        ("narration", ".md"),
        ("audio", ".mp3"),
        ("recordings", ".mp4"),
        ("animations", ".py"),
        ("terminal", ".tape"),
    ]:
        d = demo_dir / subdir
        if d.exists():
            items = [f for f in d.glob(f"*{ext}") if f.name.lower() != "readme.md"]
            if items:
                counts[subdir] = len(items)
    return counts


def run_wizard(target_dir: Path | None = None) -> InitPlan:
    """Interactive wizard that collects project info and returns an InitPlan."""
    plan = InitPlan()

    click.echo()
    click.secho("  docgen project setup", fg="cyan", bold=True)
    click.secho("  " + "=" * 22, fg="cyan")
    click.echo()

    # Detect git root
    git_root = detect_git_root(target_dir)
    if git_root:
        click.echo(f"  Git root: {git_root}")
    plan.repo_root = git_root or (target_dir or Path.cwd()).resolve()

    # Project name
    default_name = plan.repo_root.name
    plan.project_name = click.prompt(
        "  Project name", default=default_name, type=str
    )

    # Demo directory
    if target_dir:
        default_demo = str(target_dir.resolve())
    elif git_root:
        default_demo = str(git_root / "docs" / "demos")
    else:
        default_demo = str(Path.cwd() / "docs" / "demos")

    demo_str = click.prompt("  Demo assets directory", default=default_demo, type=str)
    plan.demo_dir = Path(demo_str).resolve()

    # Repo root relative to demo dir
    try:
        rel = os.path.relpath(plan.repo_root, plan.demo_dir)
    except ValueError:
        rel = str(plan.repo_root)
    click.echo(f"  Repo root relative to demo dir: {rel}")

    # .env file
    env_candidates = [
        plan.repo_root / ".env",
        plan.demo_dir / ".env",
    ]
    env_found = next((e for e in env_candidates if e.exists()), None)
    if env_found:
        plan.env_file_rel = os.path.relpath(env_found, plan.demo_dir)
        click.echo(f"  Found .env: {plan.env_file_rel}")
    else:
        env_input = click.prompt(
            "  Path to .env (for OPENAI_API_KEY, blank to skip)",
            default="", type=str,
        )
        if env_input:
            plan.env_file_rel = env_input

    # Scan existing assets
    click.echo()
    asset_counts = scan_existing_assets(plan.demo_dir)
    if asset_counts:
        click.secho("  Existing assets found:", fg="green")
        for name, count in asset_counts.items():
            click.echo(f"    {name}/: {count} files")
        click.echo()

    # Segments
    plan.existing_narrations = scan_narrations(plan.demo_dir)
    if plan.existing_narrations:
        auto_segments = infer_segments_from_narrations(plan.existing_narrations)
        click.echo(f"  Detected {len(auto_segments)} segments from narration files:")
        for s in auto_segments:
            click.echo(f"    {s['id']}: {s['name']}")

        if click.confirm("  Use these segments?", default=True):
            plan.segments = auto_segments
        else:
            plan.segments = _prompt_segments()
    else:
        num = click.prompt("  How many demo segments?", default=3, type=int)
        plan.segments = _prompt_segments(num)

    # TTS config
    click.echo()
    plan.tts_voice = click.prompt("  TTS voice", default="coral", type=str)
    plan.tts_model = click.prompt("  TTS model", default="gpt-4o-mini-tts", type=str)

    # Pre-push hook
    click.echo()
    plan.install_pre_push = click.confirm(
        "  Install pre-push validation hook?", default=True
    )

    return plan


def _prompt_segments(count: int = 0) -> list[dict[str, str]]:
    """Prompt for segment names interactively."""
    segments = []
    if count == 0:
        count = click.prompt("  How many segments?", default=3, type=int)
    for i in range(1, count + 1):
        seg_id = str(i).zfill(2)
        name = click.prompt(f"    Segment {seg_id} name", default=seg_id, type=str)
        if not name.startswith(seg_id):
            name = f"{seg_id}-{name}"
        segments.append({"id": seg_id, "name": name})
    return segments


def generate_files(plan: InitPlan) -> list[str]:
    """Generate all scaffold files and return list of created file paths."""
    created: list[str] = []

    plan.demo_dir.mkdir(parents=True, exist_ok=True)

    # Subdirectories
    for subdir in ["narration", "audio", "animations", "terminal", "terminal/rendered", "recordings"]:
        (plan.demo_dir / subdir).mkdir(parents=True, exist_ok=True)

    # docgen.yaml
    created.append(_write_config(plan))

    # Wrapper scripts
    for path in _write_wrapper_scripts(plan):
        created.append(path)

    # narration/README.md (only if narration/ is empty)
    narr_readme = plan.demo_dir / "narration" / "README.md"
    if not narr_readme.exists():
        created.append(_write_narration_readme(plan))

    # terminal/README.md with safe tape authoring guidance
    terminal_readme = plan.demo_dir / "terminal" / "README.md"
    if not terminal_readme.exists():
        created.append(_write_terminal_readme(plan))

    # Starter narration files (only for segments without existing files)
    for seg in plan.segments:
        narr_file = plan.demo_dir / "narration" / f"{seg['name']}.md"
        if not narr_file.exists():
            narr_file.write_text(
                f"Welcome to {plan.project_name}. This is the narration for {seg['name']}.\n",
                encoding="utf-8",
            )
            created.append(str(narr_file))

    # Pre-push hook
    if plan.install_pre_push:
        path = _install_pre_push_hook(plan)
        if path:
            created.append(path)

    return created


def _write_config(plan: InitPlan) -> str:
    rel_root = os.path.relpath(plan.repo_root, plan.demo_dir)

    segment_ids = [s["id"] for s in plan.segments]
    segment_names = {s["id"]: s["name"] for s in plan.segments}

    config = {
        "repo_root": rel_root,
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {
            "default": segment_ids,
            "all": segment_ids,
        },
        "segment_names": segment_names,
        "visual_map": {},
        "vhs": {
            "vhs_path": "",
            "sync_from_timing": False,
            "typing_ms_per_char": 55,
            "max_typing_sec": 3.0,
            "min_sleep_sec": 0.2,
            "render_timeout_sec": 120,
        },
        "compose": {
            "ffmpeg_timeout_sec": 300,
            "warn_stale_vhs": True,
        },
        "tts": {
            "model": plan.tts_model,
            "voice": plan.tts_voice,
            "instructions": (
                f"You are narrating a technical demo video about {plan.project_name}. "
                "Speak in a calm, professional tone. Pronounce technical terms clearly."
            ),
        },
        "concat": {
            "full-demo": segment_ids,
        },
        "validation": {
            "max_drift_sec": 2.75,
            "narration_lint": {
                "pre_tts_deny_patterns": [
                    "target duration",
                    "intended length",
                    "visual:",
                    "edit for voice",
                ],
            },
        },
        "wizard": {
            "llm_model": "gpt-4o",
            "system_prompt": (
                f"You are a technical writer creating narration scripts for demo videos about "
                f"{plan.project_name}. Write in plain spoken English suitable for text-to-speech. "
                "No markdown formatting, no headings, no bullet points. Conversational but "
                "professional tone, like a senior engineer presenting at a conference."
            ),
            "exclude_patterns": [
                "**/node_modules/**",
                "**/.pytest_cache/**",
                "**/__pycache__/**",
                "**/.venv/**",
                "**/archive/**",
            ],
        },
        "discover_tests": {
            "roots": list(plan.discover_roots),
        },
    }

    if plan.env_file_rel:
        config["env_file"] = plan.env_file_rel

    path = plan.demo_dir / "docgen.yaml"
    header = (
        f"# docgen.yaml — configuration for {plan.project_name} demo pipeline\n"
        "# See: https://github.com/jmjava/documentation-generator\n"
        "#\n"
        "# Edit this file to match your project structure, then run:\n"
        "#   docgen generate-all       # full pipeline\n"
        "#   docgen wizard             # interactive GUI\n"
        "#   docgen validate           # check recordings\n"
        "#   docgen discover-tests     # list Playwright tests; --suggest-visual-map for docgen.yaml\n\n"
    )
    path.write_text(
        header + yaml.dump(config, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return str(path)


def _write_wrapper_scripts(plan: InitPlan) -> list[str]:
    created = []

    _bash_dir = 'DEMOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'
    _venv_activate = "\n".join([
        'REPO_ROOT="$(cd "$DEMOS_DIR/../.." && pwd)"',
        'for _venv in "$DEMOS_DIR/.venv" "$REPO_ROOT/.venv"; do',
        '    [ -f "$_venv/bin/activate" ] && { source "$_venv/bin/activate"; break; }',
        'done',
    ])

    scripts = {
        "generate-all.sh": "\n".join([
            "#!/usr/bin/env bash",
            "# Full pipeline (TTS, segment visuals, compose, validate, concat). Wraps: docgen generate-all",
            "set -euo pipefail",
            _bash_dir,
            _venv_activate,
            'ARGS=()',
            'for arg in "$@"; do',
            '    if [[ "$arg" == "--dry-run" ]]; then',
            '        exec docgen --config "$DEMOS_DIR/docgen.yaml" tts --dry-run',
            '    fi',
            '    ARGS+=("$arg")',
            'done',
            'exec docgen --config "$DEMOS_DIR/docgen.yaml" generate-all "${ARGS[@]}"',
            "",
        ]),
        "compose.sh": "\n".join([
            "#!/usr/bin/env bash",
            "# Compose segments (audio + video via ffmpeg).",
            "# Wraps: docgen compose",
            "set -euo pipefail",
            _bash_dir,
            _venv_activate,
            'exec docgen --config "$DEMOS_DIR/docgen.yaml" compose "$@"',
            "",
        ]),
        "rebuild-after-audio.sh": "\n".join([
            "#!/usr/bin/env bash",
            "# Rebuild visuals and downstream stages after new audio (skips TTS).",
            "# Wraps: docgen rebuild-after-audio",
            "set -euo pipefail",
            _bash_dir,
            _venv_activate,
            'echo "Rebuild after audio (skipping TTS, using existing audio/*.mp3)"',
            'exec docgen --config "$DEMOS_DIR/docgen.yaml" rebuild-after-audio',
            "",
        ]),
        "validate.sh": "\n".join([
            "#!/usr/bin/env bash",
            "# Validate recordings: stream presence, A/V drift, narration lint.",
            "# Wraps: docgen validate --pre-push",
            "set -euo pipefail",
            _bash_dir,
            _venv_activate,
            'exec docgen --config "$DEMOS_DIR/docgen.yaml" validate --pre-push',
            "",
        ]),
    }

    for name, content in scripts.items():
        path = plan.demo_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        created.append(str(path))

    return created


def _write_narration_readme(plan: InitPlan) -> str:
    content = textwrap.dedent("""\
        # Narration scripts (TTS source)

        These Markdown files are the spoken script for demo segments.
        `docgen tts` turns them into `audio/*.mp3`.

        ## Voice-first editing

        TTS reads what you write literally. Tips:

        - Use spoken URLs: "GET slash api slash data" not `GET /api/data`
        - Spell out abbreviations the first time
        - No markdown formatting — plain spoken English only
        - Run `docgen lint` to check for leaked metadata before TTS

        ## After edits

        ```bash
        docgen tts                     # regenerate audio
        docgen rebuild-after-audio     # re-render visuals + compose + validate + concat
        ```
    """)
    path = plan.demo_dir / "narration" / "README.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_terminal_readme(plan: InitPlan) -> str:
    content = textwrap.dedent("""\
        # Terminal tape authoring (VHS)

        `.tape` files run in a real shell. Avoid real long-running commands in demos.

        ## Safe pattern: simulate output with `echo`

        Prefer:

        ```tape
        Type "echo '$ python app.py --serve'"
        Enter
        Type "echo 'Starting server on :8080'"
        Enter
        ```

        Avoid in tapes unless you really want to execute them:
        - `python ...`
        - `curl localhost ...`
        - `npm start`, `docker ...`, `kubectl ...`

        Useful checks:
        - `docgen tape-lint` (warn on risky command patterns)
        - `docgen vhs --strict` (fails on common shell error output)
    """)
    path = plan.demo_dir / "terminal" / "README.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _install_pre_push_hook(plan: InitPlan) -> str | None:
    git_root = detect_git_root(plan.demo_dir)
    if not git_root:
        click.echo("  No git root found — skipping pre-push hook")
        return None

    precommit_cfg = git_root / ".pre-commit-config.yaml"
    demo_rel = os.path.relpath(plan.demo_dir, git_root)

    hook_block = "\n".join([
        "",
        "  # Validate demo recordings (A/V drift, narration lint) before push",
        "  - repo: local",
        "    hooks:",
        "      - id: docgen-validate",
        "        name: docgen validate (demo A/V + narration lint)",
        f"        entry: bash -c 'cd {demo_rel} && docgen --config docgen.yaml validate --pre-push'",
        "        language: system",
        "        stages: [pre-push]",
        "        pass_filenames: false",
        f"        files: ^{re.escape(demo_rel)}/",
        "",
    ])

    if precommit_cfg.exists():
        existing = precommit_cfg.read_text(encoding="utf-8")
        if "docgen-validate" in existing:
            click.echo("  Pre-push hook already present in .pre-commit-config.yaml")
            return None
        precommit_cfg.write_text(existing.rstrip() + "\n" + hook_block, encoding="utf-8")
    else:
        content = "\n".join([
            "# Pre-commit hooks. Install: pip install pre-commit && pre-commit install",
            "repos:",
            "  - repo: https://github.com/pre-commit/pre-commit-hooks",
            "    rev: v4.5.0",
            "    hooks:",
            "      - id: check-added-large-files",
            "        args: ['--maxkb=1000']",
        ]) + "\n" + hook_block
        precommit_cfg.write_text(content, encoding="utf-8")

    # Try to install the hook
    try:
        subprocess.run(
            ["pre-commit", "install", "--hook-type", "pre-push"],
            cwd=str(git_root),
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        click.echo("  pre-commit not installed — run: pre-commit install --hook-type pre-push")

    return str(precommit_cfg)


def print_summary(plan: InitPlan, created: list[str]) -> None:
    click.echo()
    click.secho("  Setup complete!", fg="green", bold=True)
    click.echo()
    click.echo(f"  Created {len(created)} files in {plan.demo_dir}/")
    click.echo()
    for f in created:
        try:
            rel = os.path.relpath(f, plan.demo_dir)
        except ValueError:
            rel = f
        click.echo(f"    {rel}")
    click.echo()
    click.secho("  Next steps:", fg="cyan")
    click.echo(f"    cd {plan.demo_dir}")
    click.echo("    docgen wizard              # launch GUI to draft narrations")
    click.echo("    docgen tts --dry-run       # preview TTS text stripping")
    click.echo("    docgen validate            # check recordings")
    click.echo("    docgen generate-all        # full pipeline (see docgen generate-all --help)")
    click.echo()
    click.echo("  Run docgen yaml-generate next, then edit docgen.yaml for segments, visuals, and TTS as needed.")
    try:
        from docgen.test_discovery import node_playwright_project_ready

        if node_playwright_project_ready(plan.repo_root):
            click.echo()
            click.secho("  Playwright:", fg="cyan")
            click.echo("    docgen discover-tests --suggest-visual-map")
            click.echo("    docgen discover-tests --merge-catalog   # after tuning docgen.yaml paths")
    except Exception:
        pass
    click.echo()
