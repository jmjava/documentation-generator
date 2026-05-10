"""CLI dispatcher for the docgen tool."""

from __future__ import annotations

import os
from pathlib import Path

import click
import yaml

from docgen.config import Config
from docgen.yaml_generate import DEFAULT_LLM_MODEL


def _parse_env_file_pairs(env_path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        k = key.strip()
        if not k:
            continue
        v = val.strip().strip('"').strip("'")
        pairs.append((k, v))
    return pairs


def _docgen_env_override_mode() -> str | set[str] | None:
    """Return None (shell wins), 'all' (.env overwrites every key), or a set of keys."""
    raw = (os.environ.get("DOCGEN_ENV_OVERRIDES") or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower in ("1", "true", "yes", "*", "all"):
        return "all"
    keys = {p.strip() for p in raw.split(",") if p.strip()}
    return keys if keys else None


def _load_env(cfg: Config | None) -> None:
    """Load .env file from config if specified, so OPENAI_API_KEY etc. are available.

    By default **shell environment wins**: ``os.environ.setdefault`` does not
    replace keys already exported. Set ``DOCGEN_ENV_OVERRIDES=1`` so every key
    from the file overwrites, or ``DOCGEN_ENV_OVERRIDES=KEY1,KEY2`` for selected
    keys only.
    """
    if not cfg or not cfg.env_file or not cfg.env_file.exists():
        return
    pairs = _parse_env_file_pairs(cfg.env_file)
    mode = _docgen_env_override_mode()
    if mode == "all":
        for k, v in pairs:
            os.environ[k] = v
        return
    override_keys = mode if isinstance(mode, set) else set()
    for k, v in pairs:
        if k in override_keys:
            os.environ[k] = v
            continue
        if (
            k == "OPENAI_API_KEY"
            and v
            and os.environ.get("OPENAI_API_KEY")
        ):
            click.echo(
                "[docgen] OPENAI_API_KEY already set in the process environment; "
                "env_file value is ignored for this key (shell wins). "
                "Unset OPENAI_API_KEY or set DOCGEN_ENV_OVERRIDES=1 to load all keys "
                "from env_file, or DOCGEN_ENV_OVERRIDES=OPENAI_API_KEY to override just "
                "this key.",
                err=True,
            )
        os.environ.setdefault(k, v)


@click.group()
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=False),
    help="Path to docgen.yaml (parents of cwd are searched when omitted).",
)
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """docgen — demo generation pipeline.

    Environment: keys already set in the shell are not replaced by ``env_file``
    (see ``DOCGEN_ENV_OVERRIDES``). If no docgen.yaml is found, pass ``--config``.
    """
    ctx.ensure_object(dict)
    try:
        cfg = Config.from_yaml(config_path) if config_path else Config.discover()
    except FileNotFoundError:
        cfg = None
        click.echo(
            "[docgen] No docgen.yaml found in this directory tree; pass "
            "`--config PATH/to/docgen.yaml` or `cd` to your demos bundle directory.",
            err=True,
        )
    ctx.obj["config"] = cfg
    _load_env(cfg)


@main.command()
@click.argument("target_dir", required=False, default=None, type=click.Path())
@click.option(
    "--defaults",
    is_flag=True,
    help="Non-interactive: detect git root, infer segments from narration/*.md (or 01-intro), then write docgen.yaml.",
)
@click.option(
    "--segments-file",
    "segments_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Path to a plain-text file listing one segment stem per line "
        "(e.g. ``01-overview``). Used instead of scanning ``narration/*.md``. "
        "Lets a reset wipe narration completely and still recreate the same "
        "segment list deterministically. Requires --defaults."
    ),
)
@click.pass_context
def init(
    ctx: click.Context,
    target_dir: str | None,
    defaults: bool,
    segments_file: Path | None,
) -> None:
    """Scaffold a new project: docgen.yaml, wrapper scripts, directories.

    Optionally pass a target directory (defaults to the current directory for interactive mode,
    or ``<repo>/docs/demos`` for ``--defaults`` with no argument).

    **Start clean:** ``docgen init PATH --defaults`` then ``docgen yaml-generate``.
    """
    from docgen.init import build_defaults_plan, generate_files, print_summary, run_wizard

    td = Path(target_dir).resolve() if target_dir else None
    if defaults:
        plan = build_defaults_plan(
            td,
            segments_file=segments_file.resolve() if segments_file else None,
        )
    else:
        if segments_file is not None:
            raise click.ClickException("--segments-file requires --defaults.")
        plan = run_wizard(target_dir=td)

    created = generate_files(plan)
    print_summary(plan, created)


@main.command()
@click.option("--port", default=8501, help="Port for the wizard web server.")
@click.pass_context
def wizard(ctx: click.Context, port: int) -> None:
    """Launch the production wizard (local web GUI)."""
    from docgen.wizard import create_app

    cfg = ctx.obj["config"]
    app = create_app(cfg)
    click.echo(f"Starting docgen wizard on http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


@main.command()
@click.option("--segment", default=None, help="Generate TTS for a single segment.")
@click.option("--dry-run", is_flag=True, help="Show stripped text without calling TTS API.")
@click.pass_context
def tts(ctx: click.Context, segment: str | None, dry_run: bool) -> None:
    """Generate TTS audio from narration markdown."""
    from docgen.tts import TTSGenerator

    cfg = ctx.obj["config"]
    gen = TTSGenerator(cfg)
    gen.generate(segment=segment, dry_run=dry_run)


@main.command()
@click.pass_context
def timestamps(ctx: click.Context) -> None:
    """Extract Whisper timestamps from TTS audio -> timing.json."""
    from docgen.timestamps import TimestampExtractor

    cfg = ctx.obj["config"]
    TimestampExtractor(cfg).extract_all()


@main.command()
@click.option("--scene", default=None, help="Render a single Manim scene.")
@click.pass_context
def manim(ctx: click.Context, scene: str | None) -> None:
    """Render Manim animations."""
    from docgen.manim_runner import ManimRunner

    cfg = ctx.obj["config"]
    runner = ManimRunner(cfg)
    runner.render(scene=scene)


@main.command()
@click.argument("segments", nargs=-1)
@click.option(
    "--ffmpeg-timeout",
    default=None,
    type=int,
    help="Override ffmpeg timeout in seconds (default from docgen.yaml compose.ffmpeg_timeout_sec).",
)
@click.option(
    "--only-visual-type",
    "only_visual_types",
    multiple=True,
    help=(
        "Only compose segments whose visual_map type matches (repeatable). "
        "Useful after refreshing pre-recorded captures without re-muxing "
        "Manim segments, e.g. --only-visual-type still."
    ),
)
@click.pass_context
def compose(
    ctx: click.Context,
    segments: tuple[str, ...],
    ffmpeg_timeout: int | None,
    only_visual_types: tuple[str, ...],
) -> None:
    """Compose segments (audio + video via ffmpeg).

    Pass segment IDs to compose specific ones, or omit for the default set.
    """
    from docgen.compose import Composer, filter_segments_by_visual_types

    cfg = ctx.obj["config"]
    comp = Composer(cfg, ffmpeg_timeout_sec=ffmpeg_timeout)
    target = list(segments) if segments else list(cfg.segments_default)
    target = filter_segments_by_visual_types(cfg, target, only_visual_types)
    if only_visual_types and not target:
        raise click.ClickException(
            "[compose] No segments left after --only-visual-type filter "
            f"({', '.join(only_visual_types)})."
        )
    click.echo(f"=== Composing {len(target)} segments ===")
    comp.compose_segments(target)


@main.command()
@click.option("--max-drift", default=None, type=float, help="Max A/V drift in seconds.")
@click.option("--pre-push", is_flag=True, help="Run all checks; exit non-zero on any failure.")
@click.pass_context
def validate(ctx: click.Context, max_drift: float | None, pre_push: bool) -> None:
    """Run validation checks on composed videos (streams, drift, narration lint)."""
    from docgen.validate import Validator

    cfg = ctx.obj["config"]
    v = Validator(cfg)
    if pre_push:
        v.run_pre_push()
    else:
        report = v.run_all(max_drift_override=max_drift)
        v.print_report(report)


@main.command()
@click.option("--segment", default=None, help="Lint a single segment.")
@click.pass_context
def lint(ctx: click.Context, segment: str | None) -> None:
    """Run narration lint on all (or one) segment narration files."""
    from docgen.narration_lint import NarrationLinter

    cfg = ctx.obj["config"]
    linter = NarrationLinter(cfg)
    segments = [segment] if segment else cfg.segments_all
    issues_total = 0

    for seg_id in segments:
        seg_name = cfg.resolve_segment_name(seg_id)
        narr_dir = cfg.narration_dir
        if not narr_dir.exists():
            continue
        path = narr_dir / f"{seg_name}.md"
        if not path.exists():
            candidates = list(narr_dir.glob(f"{seg_id}-*.md"))
            path = candidates[0] if candidates else None
        if not path or not path.exists():
            click.echo(f"  [{seg_id}] no narration file")
            continue
        result = linter.lint_text(path.read_text(encoding="utf-8"))
        status = "PASS" if result.passed else "FAIL"
        click.echo(f"  [{seg_id}] {status} {seg_name}")
        for issue in result.issues:
            click.echo(f"    {issue}")
            issues_total += 1

    if issues_total:
        raise SystemExit(1)


@main.command("narration-generate")
@click.option(
    "--segment",
    default=None,
    help="Segment id (e.g. 01). Mutually exclusive with --all.",
)
@click.option(
    "--all",
    "all_segments",
    is_flag=True,
    help="Generate narration for every id in segments.all (use --force to overwrite).",
)
@click.option(
    "--extra-path",
    "extra_paths",
    multiple=True,
    type=str,
    help="Repo-root-relative source file to include (repeatable). Adds to narration_from_source.context.paths.",
)
@click.option(
    "--hint",
    "extra_hints",
    multiple=True,
    type=str,
    help="Project-owner hint for the model (repeatable). Adds to YAML hints.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print generated markdown to stdout; do not write narration/*.md.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite an existing narration file for this segment.",
)
@click.pass_context
def narration_generate(
    ctx: click.Context,
    segment: str | None,
    all_segments: bool,
    extra_paths: tuple[str, ...],
    extra_hints: tuple[str, ...],
    dry_run: bool,
    force: bool,
) -> None:
    """Generate narration ``.md`` from repo sources + owner hints via OpenAI chat.

    Configure ``narration_from_source`` in docgen.yaml (context paths/globs, hints, model).
    Requires ``OPENAI_API_KEY`` unless using a future offline stub.

    Use ``--segment <id>`` to drive a single segment, or ``--all`` to iterate
    every id in ``segments.all`` (used by full-reset orchestration).
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")
    if all_segments and segment:
        raise click.ClickException("--all and --segment are mutually exclusive")
    if not all_segments and not segment:
        raise click.ClickException("provide --segment <id> or --all")

    from docgen.narrate_from_source import generate_narration_markdown, write_narration_markdown

    cfg = ctx.obj["config"]

    if all_segments:
        ids = list((cfg.raw.get("segments") or {}).get("all") or [])
        if not ids:
            raise click.ClickException("segments.all is empty in docgen.yaml")
        for seg_id in ids:
            seg_str = str(seg_id)
            click.echo(f"=== narration-generate --segment {seg_str} ===")
            try:
                body = generate_narration_markdown(
                    cfg,
                    seg_str,
                    extra_paths=list(extra_paths),
                    extra_hints=list(extra_hints),
                )
            except ValueError as exc:
                raise click.ClickException(f"segment {seg_str}: {exc}") from exc
            if dry_run:
                click.echo(body)
                continue
            try:
                out = write_narration_markdown(cfg, seg_str, body, force=force)
            except FileExistsError as exc:
                raise click.ClickException(f"segment {seg_str}: {exc} (use --force)") from exc
            click.echo(f"  -> {out}")
        return

    assert segment is not None  # for type-checker
    try:
        body = generate_narration_markdown(
            cfg,
            segment,
            extra_paths=list(extra_paths),
            extra_hints=list(extra_hints),
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        click.echo(body)
        return

    try:
        out = write_narration_markdown(cfg, segment, body, force=force)
    except FileExistsError as exc:
        raise click.ClickException(f"{exc} (use --force)") from exc
    click.echo(f"[narration-generate] wrote {out}")


@main.command("scene-compile")
@click.argument(
    "spec_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print generated Python only; do not write animations/scenes.py.",
)
@click.pass_context
def scene_compile(ctx: click.Context, spec_path: Path, dry_run: bool) -> None:
    """Compile a declarative ``*.scene.yaml`` into ``animations/scenes.py``.

    Deterministic layout (rows of ``_box`` mobjects) — use for reliable diagrams
    or after an LLM emits **only** YAML. Schema: :mod:`docgen.scene_spec`.
    ``timing_key`` defaults from ``segment_names`` in docgen.yaml when omitted.
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")
    from docgen.manim_scene_support import SceneGenerationError
    from docgen.scene_spec import load_scene_spec
    from docgen.scene_spec_generate import inject_class_block_into_scenes_py, linted_class_block_from_spec

    cfg = ctx.obj["config"]
    raw = load_scene_spec(spec_path)
    try:
        class_block, merged = linted_class_block_from_spec(cfg, dict(raw))
    except SceneGenerationError as exc:
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        click.echo(class_block, nl=False)
        return

    sid = str(merged["segment_id"]).strip()
    class_name = str(merged["class_name"]).strip()
    scenes_path = inject_class_block_into_scenes_py(
        cfg, seg_id=sid, class_name=class_name, class_block=class_block
    )
    click.echo(
        f"[scene-compile] wrote {class_name} to {scenes_path} "
        f"(segment {sid} → timing_key {merged['timing_key']!r})"
    )


@main.command("scene-spec-generate")
@click.option(
    "--segment",
    "segment",
    default=None,
    help="Segment id (e.g. 01). Mutually exclusive with --all.",
)
@click.option(
    "--all",
    "all_segments",
    is_flag=True,
    help="Generate a scene spec for every segment in segments.all whose visual_map "
    "type is manim (or unset) and that has no scripts/*<id>*.py. "
    "--class-name is ignored with --all.",
)
@click.option(
    "--class-name",
    "class_name_override",
    default=None,
    help="Override class name (default: manim_scene_generation.segments.<id>.class_name or CamelCase+Scene). Ignored with --all.",
)
@click.option(
    "--extra-path",
    "extra_paths",
    multiple=True,
    type=str,
    help="Repo-root-relative source file (repeatable); added to manim context.paths.",
)
@click.option(
    "--hint",
    "extra_hints",
    multiple=True,
    type=str,
    help="Extra owner hint for the model (repeatable).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print prompts only; do not call OpenAI.",
)
@click.option(
    "--print-only",
    is_flag=True,
    help="Call OpenAI and print YAML to stdout; do not write a spec file by default.",
)
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(path_type=Path, dir_okay=False),
    help="Write spec YAML here (default: <animations_dir>/specs/<segment_stem>.scene.yaml).",
)
@click.option(
    "--compile",
    "do_compile",
    is_flag=True,
    help="After success, inject the compiled class into animations/scenes.py (same as scene-compile).",
)
@click.option(
    "--model",
    default=None,
    help="OpenAI chat model override (default: manim_scene_generation.model in docgen.yaml).",
)
@click.pass_context
def scene_spec_generate_cmd(
    ctx: click.Context,
    segment: str | None,
    all_segments: bool,
    class_name_override: str | None,
    extra_paths: tuple[str, ...],
    extra_hints: tuple[str, ...],
    dry_run: bool,
    print_only: bool,
    output_path: Path | None,
    do_compile: bool,
    model: str | None,
) -> None:
    """Generate a declarative ``*.scene.yaml`` via OpenAI, then optionally compile.

    The model outputs YAML only (see :mod:`docgen.scene_spec`); layout is
    deterministic in :func:`docgen.scene_spec.compile_scene_class`.
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")
    if dry_run and print_only:
        raise click.ClickException("--dry-run and --print-only are mutually exclusive")
    if all_segments and segment:
        raise click.ClickException("--all and --segment are mutually exclusive")
    if not all_segments and not segment:
        raise click.ClickException("provide --segment <id> or --all")
    if all_segments and class_name_override:
        raise click.ClickException("--class-name cannot be combined with --all")
    if all_segments and output_path:
        raise click.ClickException("--output cannot be combined with --all (per-segment paths are used)")

    from docgen.manim_scene_support import SceneGenerationError
    from docgen.scene_spec_generate import (
        generate_scene_spec,
        inject_class_block_into_scenes_py,
        linted_class_block_from_spec,
    )

    cfg = ctx.obj["config"]

    def _one_sid(sid: str) -> None:
        try:
            res = generate_scene_spec(
                cfg,
                sid,
                extra_paths=list(extra_paths),
                extra_hints=list(extra_hints),
                class_name_override=class_name_override,
                dry_run=dry_run,
                model_override=model,
            )
        except SceneGenerationError as exc:
            raise click.ClickException(f"segment {sid}: {exc}") from exc
        if dry_run:
            click.echo(res.prompt)
            return
        if print_only:
            click.echo(res.yaml_text, nl=False)
        else:
            specs_dir = cfg.animations_dir / "specs"
            specs_dir.mkdir(parents=True, exist_ok=True)
            wpath = specs_dir / f"{res.seg_name}.scene.yaml"
            wpath.write_text(res.yaml_text, encoding="utf-8")
            click.echo(f"[scene-spec-generate] wrote {wpath}")
        if do_compile:
            try:
                class_block, merged = linted_class_block_from_spec(
                    cfg, res.spec, timing_key=res.seg_name
                )
                inject_class_block_into_scenes_py(
                    cfg,
                    seg_id=merged["segment_id"],
                    class_name=merged["class_name"],
                    class_block=class_block,
                )
            except SceneGenerationError as exc:
                raise click.ClickException(str(exc)) from exc
            click.echo(
                f"[scene-spec-generate] compiled → {cfg.animations_dir / 'scenes.py'} "
                f"({res.class_name}, timing_key {res.seg_name!r})"
            )

    if all_segments:
        ids = list((cfg.raw.get("segments") or {}).get("all") or [])
        if not ids:
            raise click.ClickException("segments.all is empty in docgen.yaml")
        names = (cfg.raw.get("segment_names") or {})
        scripts_dir = cfg.base_dir / "scripts"
        for seg_id in ids:
            sid = str(seg_id)
            name = names.get(sid) or names.get(seg_id) or sid
            script_match = (
                list(scripts_dir.glob(f"*{sid}*.py")) if scripts_dir.is_dir() else []
            )
            if script_match:
                click.echo(
                    f"[scene-spec-generate --all] skip {sid} ({name}): existing capture script"
                )
                continue
            vm_row = cfg.visual_map.get(sid)
            if isinstance(vm_row, dict):
                vtype = str(vm_row.get("type", "")).strip().lower()
                if vtype and vtype != "manim":
                    click.echo(
                        f"[scene-spec-generate --all] skip {sid} ({name}): "
                        f"visual_map type is {vtype!r} (not manim)"
                    )
                    continue
            click.echo(f"=== scene-spec-generate --segment {sid} ===")
            _one_sid(sid)
        return

    assert segment is not None  # type-checker
    try:
        result = generate_scene_spec(
            cfg,
            segment,
            extra_paths=list(extra_paths),
            extra_hints=list(extra_hints),
            class_name_override=class_name_override,
            dry_run=dry_run,
            model_override=model,
        )
    except SceneGenerationError as exc:
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        click.echo(result.prompt)
        return

    if print_only:
        click.echo(result.yaml_text, nl=False)

    write_path: Path | None = None
    if not print_only:
        specs_dir = cfg.animations_dir / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        write_path = output_path or (specs_dir / f"{result.seg_name}.scene.yaml")
    elif output_path:
        write_path = output_path

    if write_path is not None:
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(result.yaml_text, encoding="utf-8")
        click.echo(f"[scene-spec-generate] wrote {write_path}")

    if do_compile:
        try:
            class_block, merged = linted_class_block_from_spec(cfg, result.spec, timing_key=result.seg_name)
            inject_class_block_into_scenes_py(
                cfg,
                seg_id=merged["segment_id"],
                class_name=merged["class_name"],
                class_block=class_block,
            )
        except SceneGenerationError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(
            f"[scene-spec-generate] compiled → {cfg.animations_dir / 'scenes.py'} "
            f"({result.class_name}, timing_key {result.seg_name!r})"
        )


@main.command("yaml-generate")
@click.option(
    "--merge-defaults/--no-merge-defaults",
    default=True,
    help="Merge safe defaults (archive exclude, optional skeleton blocks).",
)
@click.option(
    "--llm",
    is_flag=True,
    help="Call OpenAI to refresh tts.instructions and wizard.system_prompt from README/AGENTS.",
)
@click.option(
    "--model",
    default=None,
    help=f"Chat model for --llm (default: {DEFAULT_LLM_MODEL}).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print actions and merged YAML to stdout; do not write docgen.yaml.",
)
@click.option(
    "--list-gaps",
    is_flag=True,
    help="Print narration segment ids missing from segments.all; exit 1 if any.",
)
@click.option(
    "--merge-hint-segments/--no-merge-hint-segments",
    default=True,
    show_default=True,
    help="Merge segment ids from hints/*.md YAML front matter (docgen.segment.create).",
)
@click.pass_context
def yaml_generate_cmd(
    ctx: click.Context,
    merge_defaults: bool,
    llm: bool,
    model: str | None,
    dry_run: bool,
    list_gaps: bool,
    merge_hint_segments: bool,
) -> None:
    """Merge structural defaults and optionally LLM-authored TTS/wizard prose into docgen.yaml.

    Rewrites the config file with PyYAML (comments are not preserved). Use Git to review.
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")

    from docgen import yaml_generate as yg

    cfg = ctx.obj["config"]
    path = cfg.yaml_path
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    if list_gaps:
        gaps = yg.narration_not_in_segments(raw, cfg.narration_dir)
        if not gaps:
            click.echo("[yaml-generate] no narration segments missing from segments.all")
            return
        for seg_id, stem in gaps:
            click.echo(f"gap: {seg_id} ({stem}.md) not in segments.all")
        raise SystemExit(1)

    changes: list[str] = []
    if merge_defaults:
        changes.extend(yg.merge_defaults(raw, cfg, merge_hint_segments=merge_hint_segments))
    if llm:
        try:
            hints = yg.generate_llm_hints(cfg, model=model)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        yg.apply_llm_hints(raw, hints)
        changes.append("tts.instructions + wizard.system_prompt: refreshed via OpenAI")

    if not changes and not dry_run:
        click.echo("[yaml-generate] nothing to do (already up to date)")
        return

    for line in changes:
        click.echo(f"[yaml-generate] {line}")

    if dry_run:
        click.echo("--- merged yaml ---")
        click.echo(
            yaml.safe_dump(
                raw, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120
            ),
            nl=False,
        )
        return

    header = yg.default_header(path) if changes else None
    yg.write_docgen_yaml(path, raw, header=header)
    click.echo(f"[yaml-generate] wrote {path}")


@main.command("clean-bundle")
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Confirm delete without interactive prompt (required for CI/scripts).",
)
@click.option(
    "--delete-config",
    is_flag=True,
    help="Remove docgen.yaml first, then clean generated assets (paths come from the config loaded at startup).",
)
@click.option(
    "--keep-narration/--no-keep-narration",
    default=False,
    show_default=True,
    help="Keep narration/*.md segment scripts (still keeps README). Useful before docgen init reinfers segments.",
)
@click.pass_context
def clean_bundle(
    ctx: click.Context,
    yes: bool,
    delete_config: bool,
    keep_narration: bool,
) -> None:
    """Remove regenerable outputs under this bundle (animations, audio, recordings, wizard state).

    With **``--delete-config``**, ``docgen.yaml`` is removed **first**, then the same asset cleanup runs
    (using directory layout from the config that was loaded before removal).

    Does **not** remove fixtures under ``repo_root``.

    Typical fresh start: ``docgen --config docgen.yaml clean-bundle -y --delete-config [--keep-narration]``,
    then ``docgen init …`` and ``docgen yaml-generate``.
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")
    cfg = ctx.obj["config"]
    if not yes:
        click.confirm(
            "Delete bundle outputs"
            + (" and docgen.yaml" if delete_config else "")
            + "? (see docgen clean-bundle --help)",
            abort=True,
        )

    from docgen.bundle_clean import clean_bundle_regenerable_outputs

    yaml_path = cfg.yaml_path.resolve()
    if delete_config:
        if yaml_path.is_file():
            yaml_path.unlink()
            click.echo(f"[clean-bundle] removed {yaml_path}")
        else:
            click.echo(f"[clean-bundle] docgen.yaml already missing: {yaml_path}", err=True)

    summary = clean_bundle_regenerable_outputs(cfg, keep_narration=keep_narration)
    for key in sorted(summary.keys()):
        click.echo(f"[clean-bundle] {key}: {summary[key]}")


@main.command("concat")
@click.argument("concat_name", required=False)
@click.pass_context
def concat(ctx: click.Context, concat_name: str | None) -> None:
    """Concatenate full demo files from composed segments."""
    from docgen.concat import ConcatBuilder

    cfg = ctx.obj["config"]
    builder = ConcatBuilder(cfg)
    builder.build(name=concat_name)


@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing files.")
@click.pass_context
def pages(ctx: click.Context, force: bool) -> None:
    """Generate index.html, pages.yml, .gitattributes, .gitignore."""
    from docgen.pages import PagesGenerator

    cfg = ctx.obj["config"]
    gen = PagesGenerator(cfg)
    gen.generate_all(force=force)


@main.command("generate-all")
@click.option("--skip-tts", is_flag=True)
@click.option("--skip-manim", is_flag=True)
@click.option(
    "--retry-manim",
    is_flag=True,
    help="If compose hits FREEZE GUARD, clear Manim cache and retry Manim + compose once.",
)
@click.pass_context
def generate_all(
    ctx: click.Context,
    skip_tts: bool,
    skip_manim: bool,
    retry_manim: bool,
) -> None:
    """Run full pipeline: TTS -> Manim -> compose -> validate -> concat -> pages."""
    from docgen.pipeline import Pipeline

    cfg = ctx.obj["config"]
    pipeline = Pipeline(cfg)
    pipeline.run(
        skip_tts=skip_tts,
        skip_manim=skip_manim,
        retry_manim_on_freeze=retry_manim,
    )


@main.command("rebuild-after-audio")
@click.pass_context
def rebuild_after_audio(ctx: click.Context) -> None:
    """Rebuild everything after new audio: Manim -> compose -> validate -> concat."""
    from docgen.pipeline import Pipeline

    cfg = ctx.obj["config"]
    pipeline = Pipeline(cfg)
    pipeline.run(skip_tts=True)

