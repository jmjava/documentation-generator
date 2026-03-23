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
@click.pass_context
def vhs(ctx: click.Context, tape: str | None, strict: bool) -> None:
    """Render VHS terminal recordings."""
    from docgen.vhs import VHSRunner

    cfg = ctx.obj["config"]
    runner = VHSRunner(cfg)
    results = runner.render(tape=tape, strict=strict)
    for r in results:
        status = "ok" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.tape}")
        for e in r.errors:
            click.echo(f"    {e}")


@main.command()
@click.argument("segments", nargs=-1)
@click.pass_context
def compose(ctx: click.Context, segments: tuple[str, ...]) -> None:
    """Compose segments (audio + video via ffmpeg).

    Pass segment IDs to compose specific ones, or omit for the default set.
    """
    from docgen.compose import Composer

    cfg = ctx.obj["config"]
    comp = Composer(cfg)
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
@click.pass_context
def generate_all(ctx: click.Context, skip_tts: bool, skip_manim: bool, skip_vhs: bool) -> None:
    """Run full pipeline: TTS -> Manim -> VHS -> compose -> validate -> concat -> pages."""
    from docgen.pipeline import Pipeline

    cfg = ctx.obj["config"]
    pipeline = Pipeline(cfg)
    pipeline.run(skip_tts=skip_tts, skip_manim=skip_manim, skip_vhs=skip_vhs)


@main.command("rebuild-after-audio")
@click.pass_context
def rebuild_after_audio(ctx: click.Context) -> None:
    """Rebuild everything after new audio: Manim -> VHS -> compose -> validate -> concat."""
    from docgen.pipeline import Pipeline

    cfg = ctx.obj["config"]
    pipeline = Pipeline(cfg)
    pipeline.run(skip_tts=True)
