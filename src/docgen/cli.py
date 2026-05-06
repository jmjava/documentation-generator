"""CLI dispatcher for the docgen tool."""

from __future__ import annotations

import os
from pathlib import Path

import click

from docgen.config import Config


def _load_env(cfg: Config | None) -> None:
    """Load .env file from config if specified, so OPENAI_API_KEY etc. are available."""
    if cfg and cfg.env_file and cfg.env_file.exists():
        for line in cfg.env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


@click.group()
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=False),
    help="Path to docgen.yaml (auto-discovered if omitted).",
)
@click.pass_context
def main(ctx: click.Context, config_path: str | None) -> None:
    """docgen — demo generation pipeline."""
    ctx.ensure_object(dict)
    try:
        cfg = Config.from_yaml(config_path) if config_path else Config.discover()
    except FileNotFoundError:
        cfg = None
    ctx.obj["config"] = cfg
    _load_env(cfg)


@main.command()
@click.argument("target_dir", required=False, default=None, type=click.Path())
@click.pass_context
def init(ctx: click.Context, target_dir: str | None) -> None:
    """Scaffold a new project: docgen.yaml, wrapper scripts, directories.

    Optionally pass a target directory (defaults to current directory).
    """
    from docgen.init import generate_files, print_summary, run_wizard

    target = Path(target_dir).resolve() if target_dir else None
    plan = run_wizard(target_dir=target)
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
@click.option("--source", default="playwright-capture.mp4", help="Output filename under terminal/rendered/.")
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
    """Capture a browser demo video using Playwright."""
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
    help="Path to *.docgen.yaml sidecar OR <path>.py::<test_name> for @pytest.mark.docgen.",
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
    """Render a single per-function demo video from a declarative manifest."""
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
@click.option("--segment", required=True, help="Segment id (e.g. 01); output name uses segment_names if set.")
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
    segment: str,
    extra_paths: tuple[str, ...],
    extra_hints: tuple[str, ...],
    dry_run: bool,
    force: bool,
) -> None:
    """Generate narration ``.md`` from repo sources + owner hints via OpenAI chat.

    Configure ``narration_from_source`` in docgen.yaml (context paths/globs, hints, model).
    Requires ``OPENAI_API_KEY`` unless using a future offline stub.
    """
    if ctx.obj.get("config") is None:
        raise click.ClickException("No docgen.yaml found (use --config PATH).")

    from docgen.narrate_from_source import generate_narration_markdown, write_narration_markdown

    cfg = ctx.obj["config"]
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


@main.command()
@click.option("--config-name", "concat_name", default=None, help="Concat config name.")
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
        click.echo("[discover-tests] no tests parsed (is `npx playwright test --list` working?)")

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
            click.echo(f"[discover-tests] --dry-run: would merge {n} new catalog entr(y/ies)")
            return
        if n == 0:
            click.echo("[discover-tests] catalog unchanged (no new entry ids)")
            return
        save_catalog(cat_path, data)
        click.echo(f"[discover-tests] merged {n} new entr(y/ies) → {cat_path}")


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
