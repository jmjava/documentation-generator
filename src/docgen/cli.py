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
    "--discover-root",
    "discover_roots",
    multiple=True,
    help=(
        "Repo-relative root for discover-tests (repeatable). "
        "Default: '.' plus any directory under the repo with a Playwright signal "
        "(`@playwright/test`/`playwright` in package.json or a `playwright.config.{js,ts,mjs,cjs}`)."
    ),
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
    discover_roots: tuple[str, ...],
    segments_file: Path | None,
) -> None:
    """Scaffold a new project: docgen.yaml, wrapper scripts, directories.

    Optionally pass a target directory (defaults to current directory for interactive mode,
    or repo ``docs/demos`` for ``--defaults`` with no argument).

    **Start clean:** ``docgen init PATH --defaults`` then ``docgen yaml-generate``.
    """
    from docgen.init import build_defaults_plan, generate_files, print_summary, run_wizard

    td = Path(target_dir).resolve() if target_dir else None
    if defaults:
        plan = build_defaults_plan(
            td,
            discover_roots=discover_roots,
            segments_file=segments_file.resolve() if segments_file else None,
        )
    else:
        if discover_roots:
            raise click.ClickException("--discover-root requires --defaults.")
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
@click.option("--tape", default=None, help="Render a single VHS tape.")
@click.option("--strict", is_flag=True, help="Fail on any unexpected stderr output.")
@click.option(
    "--timeout",
    "render_timeout_sec",
    default=None,
    type=int,
    help="Override VHS per-tape timeout seconds (default from docgen.yaml vhs.render_timeout_sec).",
)
@click.pass_context
def vhs(
    ctx: click.Context,
    tape: str | None,
    strict: bool,
    render_timeout_sec: int | None,
) -> None:
    """Render VHS terminal recordings."""
    from docgen.vhs import VHSRunner

    cfg = ctx.obj["config"]
    runner = VHSRunner(cfg)
    results = runner.render(tape=tape, strict=strict, timeout_sec=render_timeout_sec)
    for r in results:
        status = "ok" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.tape}")
        for e in r.errors:
            click.echo(f"    {e}")


@main.command()
@click.option(
    "--script",
    "script_path",
    default=None,
    help="Python script to execute for browser actions (required for standalone mode).",
)
@click.option("--url", default=None, help="Target URL for browser capture.")
@click.option(
    "--source",
    default="playwright-capture.mp4",
    help=(
        "Output path: basename only → terminal/rendered/<name>; a relative path "
        "with a directory (e.g. rendered/foo.mp4) is resolved under the bundle "
        "base_dir, not under terminal/rendered/."
    ),
)
@click.option("--width", default=1920, type=int, help="Browser viewport width.")
@click.option("--height", default=1080, type=int, help="Browser viewport height.")
@click.option("--timeout", "timeout_sec", default=120, type=int, help="Capture timeout in seconds.")
@click.pass_context
def playwright(
    ctx: click.Context,
    script_path: str | None,
    url: str | None,
    source: str,
    width: int,
    height: int,
    timeout_sec: int,
) -> None:
    """Capture a browser demo video using Playwright.

    Requires a loaded docgen.yaml: run from your bundle directory, or prefix the
    command with ``--config path/to/docgen.yaml`` (e.g.
    ``docgen --config docs/demos/docgen.yaml playwright ...``).
    """
    from docgen.playwright_runner import PlaywrightRunner

    cfg = ctx.obj["config"]
    runner = PlaywrightRunner(cfg)
    video = runner.capture(
        script=script_path,
        output=source,
        url=url,
        viewport={"width": width, "height": height},
        timeout_sec=timeout_sec,
    )
    click.echo(f"[playwright] captured: {video}")


@main.command("demo-function")
@click.option(
    "--manifest",
    "manifest_arg",
    required=True,
    help="*.docgen.yaml, Playwright *.spec.ts/.tsx, or <path>.py::<test> (@pytest.mark.docgen).",
)
@click.option(
    "--output",
    "output_dir_arg",
    default=None,
    type=click.Path(file_okay=False),
    help="Output directory for rendered.mp4, poster.png, fragment.txt, manifest.json.",
)
@click.option(
    "--output-dir",
    "output_dir_legacy",
    default=None,
    type=click.Path(file_okay=False),
    hidden=True,
    help="Deprecated alias for --output.",
)
@click.option(
    "--cache-dir",
    "cache_dir_arg",
    default=None,
    type=click.Path(file_okay=False),
    help="Optional cache directory keyed by sha256(identifier+intent+fixtures).",
)
@click.option(
    "--no-narration",
    is_flag=True,
    help="Skip TTS even if OPENAI_API_KEY is set.",
)
@click.option(
    "--grep",
    "grep_arg",
    default=None,
    help="Playwright test title filter when --manifest is a .ts/.tsx spec (or overrides YAML).",
)
@click.pass_context
def demo_function(
    ctx: click.Context,
    manifest_arg: str,
    output_dir_arg: str | None,
    output_dir_legacy: str | None,
    grep_arg: str | None,
    cache_dir_arg: str | None,
    no_narration: bool,
) -> None:
    """Render one short tutorial/demo MP4. Primary path: **Playwright** (spec or declarative
    browser manifest). ``kind: cli`` + VHS is **legacy** and may be deprecated; prefer **Manim**
    (long-form) or **Playwright** (UI) for new work.
    """
    from docgen.demo_function import run_cli

    out = output_dir_arg or output_dir_legacy
    if not out:
        raise click.UsageError("Missing required option '--output' (directory for rendered artifacts).")

    code = run_cli(
        manifest_arg=manifest_arg,
        output_dir_arg=out,
        grep=grep_arg,
        cache_dir_arg=cache_dir_arg,
        no_narration=no_narration,
    )
    if code != 0:
        raise SystemExit(code)


@main.command("tape-lint")
@click.option("--tape", default=None, help="Lint a single tape name or pattern.")
@click.pass_context
def tape_lint(ctx: click.Context, tape: str | None) -> None:
    """Lint VHS tapes for potentially real/hanging commands."""
    from docgen.vhs import VHSRunner

    cfg = ctx.obj["config"]
    runner = VHSRunner(cfg)
    reports = runner.lint_tapes(tape=tape)
    if not reports:
        click.echo("No tape files found.")
        return

    total_issues = 0
    for report in reports:
        if report.issues:
            click.echo(f"[WARN] {report.tape}")
            for issue in report.issues:
                click.echo(f"  - {issue}")
                total_issues += 1
        else:
            click.echo(f"[ok] {report.tape}")

    if total_issues:
        raise SystemExit(1)


@main.command("sync-vhs")
@click.option("--segment", default=None, help="Sync tape(s) for one segment ID/name.")
@click.option("--dry-run", is_flag=True, help="Preview updates without writing files.")
@click.pass_context
def sync_vhs(ctx: click.Context, segment: str | None, dry_run: bool) -> None:
    """Sync VHS Sleep durations from animations/timing.json."""
    from docgen.tape_sync import TapeSynchronizer

    cfg = ctx.obj["config"]
    TapeSynchronizer(cfg).sync(segment=segment, dry_run=dry_run)


@main.command()
@click.argument("segments", nargs=-1)
@click.option(
    "--ffmpeg-timeout",
    default=None,
    type=int,
    help="Override ffmpeg timeout in seconds (default from docgen.yaml compose.ffmpeg_timeout_sec).",
)
@click.pass_context
def compose(ctx: click.Context, segments: tuple[str, ...], ffmpeg_timeout: int | None) -> None:
    """Compose segments (audio + video via ffmpeg).

    Pass segment IDs to compose specific ones, or omit for the default set.
    """
    from docgen.compose import Composer

    cfg = ctx.obj["config"]
    comp = Composer(cfg, ffmpeg_timeout_sec=ffmpeg_timeout)
    target = list(segments) if segments else cfg.segments_default
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


@main.command("per-function-generate")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing per-function/<slug>.docgen.yaml.",
)
@click.option(
    "--list-only",
    is_flag=True,
    help="Print discovered Playwright (project, spec, test) tuples and exit; do not call OpenAI.",
)
@click.option(
    "--model",
    default=None,
    help="OpenAI model override (default: per_function_generate.model in docgen.yaml or gpt-4o-mini).",
)
@click.pass_context
def per_function_generate(
    ctx: click.Context,
    force: bool,
    list_only: bool,
    model: str | None,
) -> None:
    """Discover raw Playwright specs and write ``per-function/<slug>.docgen.yaml`` manifests via OpenAI.

    Each manifest is Category C output under ``<base_dir>/per-function/`` and is
    consumable by ``docgen demo-function``: ``demonstration.kind: playwright``
    + ``spec`` + ``grep`` + ``cwd`` triggers spec-record mode (``npx playwright
    test --trace=on --video=on`` against the project's own ``webServer:``).
    The manifest also embeds ``narration_steps`` so the renderer can sync each
    spoken sentence to the matching trace event without a second LLM call.

    Requires ``OPENAI_API_KEY`` unless ``--list-only``.
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")

    from docgen.per_function import (
        discover_playwright_specs,
        per_function_output_dir,
        write_per_function_manifests,
    )

    cfg = ctx.obj["config"]
    bindings = discover_playwright_specs(cfg.repo_root)
    if not bindings:
        click.echo(
            "[per-function-generate] no Playwright projects with discoverable tests "
            "(need package.json + @playwright/test + playwright.config.* + npm install).",
        )
        return

    if list_only:
        click.echo(f"[per-function-generate] discovered {len(bindings)} test(s):")
        for b in bindings:
            try:
                rel_spec = b.spec_path.relative_to(cfg.repo_root)
            except ValueError:
                rel_spec = b.spec_path
            click.echo(f"  - slug={b.slug}  spec={rel_spec}::{b.test_title}")
        return

    out_dir = per_function_output_dir(cfg)
    click.echo(
        f"[per-function-generate] generating {len(bindings)} manifest(s) under {out_dir} "
        f"(force={force})",
    )
    try:
        results = write_per_function_manifests(
            cfg, bindings=bindings, model=model, force=force
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    if not results:
        click.echo("[per-function-generate] all manifests already exist (pass --force to regenerate).")
        return
    for r in results:
        steps_n = len(r.manifest.get("narration_steps", []))
        click.echo(f"  -> {r.manifest_path.name}  ({steps_n} narration steps)")


@main.command("per-function-render")
@click.option(
    "--manifest",
    "manifest_filter",
    default=None,
    help="Render only the manifest with this slug (e.g. 'home-greeting'); default: all.",
)
@click.option(
    "--no-narration",
    is_flag=True,
    help="Render visual-only clips (skips OPENAI_API_KEY check; no TTS).",
)
@click.pass_context
def per_function_render(
    ctx: click.Context,
    manifest_filter: str | None,
    no_narration: bool,
) -> None:
    """Render every ``per-function/*.docgen.yaml`` to ``recordings/per-function/<slug>/``.

    Wraps ``docgen demo-function`` for batch use. Each manifest points at a real
    Playwright spec via ``demonstration.spec`` / ``grep`` / ``cwd``; the renderer
    shells out to ``npx playwright test --trace=on --video=on``, which reads the
    project's own ``playwright.config.*`` ``webServer:`` block to start the dev
    server, runs the test against the real app, records video + trace, then tears
    the server down. Trace timestamps drive ``narration_steps`` syncing.

    Outputs land at:

    \b
      recordings/per-function/<slug>/rendered.mp4
      recordings/per-function/<slug>/poster.png
      recordings/per-function/<slug>/manifest.json
      recordings/per-function/<slug>.mp4   (stable top-level alias)
      recordings/per-function/<slug>.poster.png
    """
    import shutil
    import sys

    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")

    from docgen.demo_function import (
        ManifestError,
        PlaceholderManifest,
        ToolingMissingError,
        load_manifest,
        render,
    )
    from docgen.per_function import per_function_output_dir

    cfg = ctx.obj["config"]
    manifest_dir = per_function_output_dir(cfg)
    if not manifest_dir.is_dir():
        click.echo(
            f"[per-function-render] no per-function dir found at {manifest_dir}; "
            "run `docgen per-function-generate` first.",
        )
        return

    candidates = sorted(manifest_dir.glob("*.docgen.yaml"))
    if not candidates:
        click.echo(
            f"[per-function-render] no manifests under {manifest_dir}; "
            "run `docgen per-function-generate` first.",
        )
        return
    if manifest_filter:
        candidates = [
            p for p in candidates if p.stem.removesuffix(".docgen") == manifest_filter
        ]
        if not candidates:
            raise click.ClickException(
                f"no manifest matched --manifest={manifest_filter!r} in {manifest_dir}"
            )

    out_root = cfg.recordings_dir / "per-function"
    out_root.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[str, str]] = []
    for manifest_path in candidates:
        slug = manifest_path.name.removesuffix(".docgen.yaml")
        click.echo(f"=== per-function-render: {slug} ===")
        try:
            manifest = load_manifest(manifest_path)
        except (ManifestError, FileNotFoundError) as exc:
            failures.append((slug, f"load: {exc}"))
            click.echo(f"  ERROR: {exc}", err=True)
            continue

        out_dir = out_root / slug
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = render(
                manifest,
                out_dir,
                no_narration=no_narration,
                stderr=sys.stderr,
            )
        except (
            ManifestError,
            PlaceholderManifest,
            ToolingMissingError,
            RuntimeError,
        ) as exc:
            failures.append((slug, str(exc)))
            click.echo(f"  ERROR: {exc}", err=True)
            continue

        rendered = result.output_dir / "rendered.mp4"
        poster = result.output_dir / "poster.png"
        alias_mp4 = out_root / f"{slug}.mp4"
        alias_poster = out_root / f"{slug}.poster.png"
        if rendered.is_file():
            shutil.copyfile(rendered, alias_mp4)
        if poster.is_file():
            shutil.copyfile(poster, alias_poster)
        click.echo(f"  -> {alias_mp4}")

    if failures:
        msg = "; ".join(f"{slug}: {err}" for slug, err in failures)
        raise click.ClickException(f"per-function-render failures: {msg}")


@main.command("scene-generate")
@click.option(
    "--segment",
    default=None,
    help="Segment id (e.g. 08). Mutually exclusive with --all.",
)
@click.option(
    "--all",
    "all_segments",
    is_flag=True,
    help="Generate a scene class for every segment in segments.all that has no "
    "VHS tape under <terminal_dir>/<name>.tape and no capture script under "
    "scripts/*<id>*.py (Manim is the fallback visual source).",
)
@click.option(
    "--class-name",
    "class_name_override",
    default=None,
    help="Override the generated class name (defaults to manim_scene_generation.segments.<id>.class_name "
    "or CamelCase(segment_name)+Scene). Ignored with --all.",
)
@click.option(
    "--extra-path",
    "extra_paths",
    multiple=True,
    type=str,
    help="Repo-root-relative source file to include (repeatable). Adds to manim_scene_generation.context.paths.",
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
    help="Print the assembled prompt to stdout; do not call OpenAI or write scenes.py.",
)
@click.option(
    "--print-only",
    is_flag=True,
    help="Call OpenAI and validate the response, but print the class to stdout instead of writing it.",
)
@click.pass_context
def scene_generate(
    ctx: click.Context,
    segment: str | None,
    all_segments: bool,
    class_name_override: str | None,
    extra_paths: tuple[str, ...],
    extra_hints: tuple[str, ...],
    dry_run: bool,
    print_only: bool,
) -> None:
    """Generate (or regenerate) a Manim scene class for a segment via OpenAI.

    Reads narration/<seg>.md + animations/timing.json + manim_scene_generation
    settings from docgen.yaml, then writes a single class block into
    animations/scenes.py between idempotent marker comments. Re-running the
    command replaces the block in place.

    Use ``--segment <id>`` for one segment, or ``--all`` to iterate every id in
    ``segments.all`` whose visual source is not already a VHS tape or a
    capture script (used by full-reset orchestration so an init-from-empty
    bundle gets a Manim scene per segment by default).
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")
    if all_segments and segment:
        raise click.ClickException("--all and --segment are mutually exclusive")
    if not all_segments and not segment:
        raise click.ClickException("provide --segment <id> or --all")
    if all_segments and class_name_override:
        raise click.ClickException("--class-name cannot be combined with --all")

    from docgen.scene_generate import SceneGenerationError, generate_scene

    cfg = ctx.obj["config"]

    if all_segments:
        ids = list((cfg.raw.get("segments") or {}).get("all") or [])
        if not ids:
            raise click.ClickException("segments.all is empty in docgen.yaml")
        names = (cfg.raw.get("segment_names") or {})
        terminal_dir = cfg.terminal_dir
        scripts_dir = cfg.base_dir / "scripts"
        for seg_id in ids:
            sid = str(seg_id)
            name = names.get(sid) or names.get(seg_id) or sid
            tape = terminal_dir / f"{name}.tape"
            script_match = (
                list(scripts_dir.glob(f"*{sid}*.py")) if scripts_dir.is_dir() else []
            )
            if tape.is_file() or script_match:
                click.echo(
                    f"[scene-generate --all] skip {sid} ({name}): existing visual "
                    f"{'tape' if tape.is_file() else 'capture script'}"
                )
                continue
            click.echo(f"=== scene-generate --segment {sid} ===")
            try:
                result = generate_scene(
                    cfg,
                    sid,
                    extra_paths=list(extra_paths),
                    extra_hints=list(extra_hints),
                    class_name_override=None,
                    dry_run=dry_run,
                    print_only=print_only,
                )
            except SceneGenerationError as exc:
                raise click.ClickException(f"segment {sid}: {exc}") from exc
            if dry_run:
                click.echo(result.prompt)
                continue
            if print_only:
                click.echo(result.cleaned_code)
                continue
            click.echo(
                f"  -> {result.class_name} in {result.scenes_path} "
                f"(segment {result.seg_id} → {result.seg_name})"
            )
        return

    assert segment is not None  # type-checker
    try:
        result = generate_scene(
            cfg,
            segment,
            extra_paths=list(extra_paths),
            extra_hints=list(extra_hints),
            class_name_override=class_name_override,
            dry_run=dry_run,
            print_only=print_only,
        )
    except SceneGenerationError as exc:
        raise click.ClickException(str(exc)) from exc

    if dry_run:
        click.echo(result.prompt)
        return
    if print_only:
        click.echo(result.cleaned_code)
        return
    click.echo(
        f"[scene-generate] wrote {result.class_name} to {result.scenes_path} "
        f"(segment {result.seg_id} → {result.seg_name})"
    )


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
    from docgen.scene_generate import SceneGenerationError
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
    required=True,
    help="Segment id (e.g. 01) matching narration and segment_names.",
)
@click.option(
    "--class-name",
    "class_name_override",
    default=None,
    help="Override class name (default: manim_scene_generation.segments.<id>.class_name or CamelCase+Scene).",
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
    segment: str,
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

    from docgen.scene_generate import SceneGenerationError
    from docgen.scene_spec_generate import (
        generate_scene_spec,
        inject_class_block_into_scenes_py,
        linted_class_block_from_spec,
    )

    cfg = ctx.obj["config"]
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
    "--reset-catalog/--no-reset-catalog",
    default=True,
    show_default=True,
    help="Also clear catalog entries at repo root (docgen.catalog.yaml).",
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
    reset_catalog: bool,
    delete_config: bool,
    keep_narration: bool,
) -> None:
    """Remove regenerable outputs under this bundle (animations, audio, terminal, recordings, wizard state).

    With **``--delete-config``**, ``docgen.yaml`` is removed **first**, then the same asset cleanup runs
    (using directory layout from the config that was loaded before removal).

    Does **not** remove ``per-function/*.docgen.yaml`` / HTML, or fixtures under ``repo_root``.

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
    if reset_catalog:
        from docgen import __version__ as docgen_version
        from docgen.source_catalog import reset_catalog_for_repo

        reset_catalog_for_repo(
            catalog_path=cfg.catalog_file_path,
            repo_root=cfg.repo_root,
            docgen_version=docgen_version,
        )
        click.echo(f"[clean-bundle] catalog reset -> {cfg.catalog_file_path}")


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
@click.option("--skip-vhs", is_flag=True)
@click.option("--skip-tape-sync", is_flag=True, help="Skip optional sync-vhs stage after timestamps.")
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
    skip_vhs: bool,
    skip_tape_sync: bool,
    retry_manim: bool,
) -> None:
    """Run full pipeline: TTS -> Manim -> VHS -> compose -> validate -> concat -> pages."""
    from docgen.pipeline import Pipeline

    cfg = ctx.obj["config"]
    pipeline = Pipeline(cfg)
    pipeline.run(
        skip_tts=skip_tts,
        skip_manim=skip_manim,
        skip_vhs=skip_vhs,
        skip_tape_sync=skip_tape_sync,
        retry_manim_on_freeze=retry_manim,
    )


@main.command("rebuild-after-audio")
@click.option("--skip-tape-sync", is_flag=True, help="Skip optional sync-vhs stage after timestamps.")
@click.pass_context
def rebuild_after_audio(ctx: click.Context, skip_tape_sync: bool) -> None:
    """Rebuild everything after new audio: Manim -> VHS -> compose -> validate -> concat."""
    from docgen.pipeline import Pipeline

    cfg = ctx.obj["config"]
    pipeline = Pipeline(cfg)
    pipeline.run(skip_tts=True, skip_tape_sync=skip_tape_sync)


@main.group("catalog")
@click.pass_context
def catalog_cmd(ctx: click.Context) -> None:
    """Create, inspect, and update ``docgen.catalog.yaml`` (incremental regen metadata)."""
    if ctx.obj.get("config") is None:
        raise click.ClickException(
            "No docgen.yaml found (use --config PATH). Catalog commands need a project config."
        )


@catalog_cmd.command("init")
@click.option(
    "--force",
    is_flag=True,
    help="Write a fresh catalog file; with --force and an existing file, keep entries but reset header metadata.",
)
@click.pass_context
def catalog_init(ctx: click.Context, force: bool) -> None:
    """Create ``docgen.catalog.yaml`` if missing (default: under repo root)."""
    from docgen import __version__ as docgen_version
    from docgen.source_catalog import load_catalog, new_catalog, save_catalog

    cfg = ctx.obj["config"]
    path = cfg.catalog_file_path
    if path.exists() and not force:
        click.echo(f"[catalog] already exists: {path}")
        return
    if path.exists() and force:
        try:
            old = load_catalog(path)
            data = new_catalog(repo_root=cfg.repo_root, docgen_version=docgen_version)
            data["entries"] = old.get("entries", [])
        except (OSError, ValueError):
            data = new_catalog(repo_root=cfg.repo_root, docgen_version=docgen_version)
    else:
        data = new_catalog(repo_root=cfg.repo_root, docgen_version=docgen_version)
    save_catalog(path, data)
    click.echo(f"[catalog] wrote {path}")


@catalog_cmd.command("reset")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation (for non-interactive CI).",
)
@click.pass_context
def catalog_reset(ctx: click.Context, yes: bool) -> None:
    """Clear every catalog entry (fresh incremental state). Header/metadata only."""
    from docgen import __version__ as docgen_version
    from docgen.source_catalog import reset_catalog_for_repo

    cfg = ctx.obj["config"]
    path = cfg.catalog_file_path
    if not yes and not click.confirm(f"Wipe all entries in {path}?", default=False):
        click.echo("[catalog] aborted")
        return
    reset_catalog_for_repo(
        catalog_path=path,
        repo_root=cfg.repo_root,
        docgen_version=docgen_version,
    )
    click.echo(f"[catalog] reset (empty entries) -> {path}")


@catalog_cmd.command("stale")
@click.option(
    "--quiet",
    is_flag=True,
    help="No per-id lines; only set exit code.",
)
@click.pass_context
def catalog_stale(ctx: click.Context, quiet: bool) -> None:
    """Exit 1 if any catalog entry needs regeneration, else 0.

    Honors ``DOCGEN_CATALOG_FORCE_IDS``, ``DOCGEN_CATALOG_FORCE_ALL``, and per-entry
    ``policy.regenerate`` (see ``docgen.source_catalog``).
    """
    from docgen.source_catalog import (
        entry_should_run,
        force_ids_from_env,
        global_force_from_env,
        load_catalog,
    )

    cfg = ctx.obj["config"]
    path = cfg.catalog_file_path
    if not path.exists():
        click.echo(f"[catalog] missing: {path} — run `docgen catalog init`", err=True)
        raise SystemExit(1)
    data = load_catalog(path)
    gf = global_force_from_env()
    fids = force_ids_from_env()
    stale_ids: list[str] = []
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id", ""))
        if entry_should_run(entry, cfg.repo_root, global_force=gf, force_ids=fids):
            stale_ids.append(eid or "(no id)")
    if not quiet:
        for sid in stale_ids:
            click.echo(f"stale: {sid}")
    if stale_ids:
        raise SystemExit(1)
    click.echo("[catalog] nothing stale")
    raise SystemExit(0)


@catalog_cmd.command("refresh")
@click.option(
    "--clear-pins",
    is_flag=True,
    help="Clear ``policy.regenerate`` / ``regenerate`` pins after refreshing fingerprints.",
)
@click.pass_context
def catalog_refresh(ctx: click.Context, clear_pins: bool) -> None:
    """Recompute ``fingerprints.inputs`` for every entry and save the catalog."""
    from docgen.source_catalog import (
        clear_regenerate_pin,
        load_catalog,
        refresh_entry_fingerprints,
        save_catalog,
    )

    cfg = ctx.obj["config"]
    path = cfg.catalog_file_path
    if not path.exists():
        raise click.ClickException(f"Missing catalog: {path} — run `docgen catalog init`")
    data = load_catalog(path)
    n = 0
    for entry in data.get("entries", []):
        if not isinstance(entry, dict):
            continue
        refresh_entry_fingerprints(entry, cfg.repo_root)
        if clear_pins:
            if clear_regenerate_pin(entry):
                n += 1
    save_catalog(path, data)
    msg = f"[catalog] refreshed fingerprints → {path}"
    if clear_pins and n:
        msg += f" (cleared {n} regenerate pin(s))"
    click.echo(msg)


@main.command("discover-tests")
@click.option(
    "--repo-root",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Repository root (Node project). Default: config repo_root when docgen.yaml is loaded.",
)
@click.option(
    "--format",
    type=click.Choice(["yaml", "json", "catalog"]),
    default="yaml",
    help="yaml: list; json: machine list; catalog: entry dicts for merge.",
)
@click.option(
    "--merge-catalog",
    is_flag=True,
    help="Append new catalog entries (requires docgen.yaml for catalog path).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="With --merge-catalog: print actions only, do not write catalog.",
)
@click.option(
    "--suggest-visual-map",
    is_flag=True,
    help="After the list, print a suggested docgen.yaml ``visual_map`` block (``playwright_test``).",
)
@click.option(
    "--visual-map-start",
    type=str,
    default="90",
    show_default=True,
    help="First numeric segment key for --suggest-visual-map (e.g. 90 → 90, 91, …).",
)
@click.option(
    "--write-suggest-visual-map",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Write --suggest-visual-map output to this file instead of printing it.",
)
@click.option(
    "--playwright-insights",
    is_flag=True,
    help="Print best-effort fields parsed from the first ``playwright.config.*`` found (JSON).",
)
@click.pass_context
def discover_tests(
    ctx: click.Context,
    repo_root: str | None,
    format: str,
    merge_catalog: bool,
    dry_run: bool,
    suggest_visual_map: bool,
    visual_map_start: str,
    write_suggest_visual_map: Path | None,
    playwright_insights: bool,
) -> None:
    """List Node ``@playwright/test`` cases via ``playwright test --list`` (no tests executed)."""
    from dataclasses import asdict
    import json as json_lib

    from docgen import __version__ as docgen_version
    from docgen.source_catalog import load_catalog, merge_entries, new_catalog, save_catalog
    from docgen.test_discovery import (
        discover_all_node_playwright_tests,
        discover_tests_yaml_lines,
        find_playwright_config,
        format_suggested_visual_map_yaml,
        node_playwright_project_ready,
        parse_playwright_config_insights,
    )

    cfg = ctx.obj.get("config")
    if cfg is not None:
        rr = cfg.repo_root.resolve()
        scan_roots = [Path(repo_root).resolve()] if repo_root else list(cfg.discover_tests_scan_roots)
    else:
        if repo_root is None:
            raise click.ClickException("Pass --repo-root or run with docgen.yaml (--config).")
        rr = Path(repo_root).resolve()
        scan_roots = [rr]

    ready = [r for r in scan_roots if node_playwright_project_ready(r)]
    if not ready:
        roots_msg = ", ".join(str(r) for r in scan_roots)
        raise click.ClickException(
            "No Node @playwright/test project under any scan root "
            f"(need playwright.config.* and @playwright/test in package.json): {roots_msg}"
        )

    tests = discover_all_node_playwright_tests(rr, scan_roots)
    if not tests:
        click.echo(
            "[discover-tests] no tests parsed (is `npx playwright test --list` working?)",
            err=True,
        )

    if format == "json":
        click.echo(json_lib.dumps([asdict(t) for t in tests], indent=2))
    elif format == "catalog":
        click.echo(json_lib.dumps([t.catalog_entry() for t in tests], indent=2))
    else:
        click.echo(discover_tests_yaml_lines(tests), nl=False)

    if playwright_insights:
        ins: dict[str, object] = {}
        for root in scan_roots:
            pcfg = find_playwright_config(root)
            if pcfg:
                ins = parse_playwright_config_insights(pcfg)
                ins["_config_path"] = str(pcfg.resolve().relative_to(rr)) if pcfg.is_relative_to(rr) else str(pcfg)
                break
        click.echo(json_lib.dumps(ins, indent=2))

    suggest_body = ""
    if suggest_visual_map or write_suggest_visual_map is not None:
        suggest_body = format_suggested_visual_map_yaml(tests, segment_key_start=visual_map_start)
    if write_suggest_visual_map is not None:
        write_suggest_visual_map.parent.mkdir(parents=True, exist_ok=True)
        write_suggest_visual_map.write_text(suggest_body, encoding="utf-8")
        click.echo(f"[discover-tests] wrote suggested visual_map → {write_suggest_visual_map}")
    elif suggest_visual_map and suggest_body:
        click.echo("\n---\n")
        click.echo(suggest_body, nl=False)

    if merge_catalog:
        if cfg is None:
            raise click.ClickException("--merge-catalog requires docgen.yaml (use --config).")
        cat_path = cfg.catalog_file_path
        if cat_path.exists():
            data = load_catalog(cat_path)
        else:
            data = new_catalog(repo_root=cfg.repo_root, docgen_version=docgen_version)
        n = merge_entries(data, [t.catalog_entry() for t in tests], replace_existing=False)
        if dry_run:
            click.echo(
                f"[discover-tests] --dry-run: would merge {n} new catalog entr(y/ies)",
                err=True,
            )
            return
        if n == 0:
            click.echo("[discover-tests] catalog unchanged (no new entry ids)", err=True)
            return
        save_catalog(cat_path, data)
        click.echo(f"[discover-tests] merged {n} new entr(y/ies) → {cat_path}", err=True)


@main.group("self")
def self_cmd() -> None:
    """Resources bundled with the installed package (works after ``pip install docgen``)."""


@self_cmd.command("catalog-issue-template")
@click.option(
    "--path",
    "path_only",
    is_flag=True,
    help="Print only the absolute path to the template file (for gh --body-file).",
)
def self_catalog_issue_template(path_only: bool) -> None:
    """Emit the catalog CI workflow GitHub issue template (markdown).

    Pipe to ``gh issue create --body-file -`` or use ``--path`` with ``--body-file``.
    """
    from docgen.bundled import catalog_workflow_issue_template_path, read_catalog_workflow_issue_template

    p = catalog_workflow_issue_template_path()
    if not p.is_file():
        raise click.ClickException(f"Bundled template missing from package install: {p}")
    if path_only:
        click.echo(str(p.resolve()))
    else:
        click.echo(read_catalog_workflow_issue_template(), nl=False)
