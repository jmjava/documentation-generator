"""narrate_from_source: merge settings, collect snippets, generate markdown."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from docgen.config import Config
from docgen.narrate_from_source import (
    build_owner_hints_guidance,
    collect_source_snippets,
    generate_narration_markdown,
    merged_narration_from_source_settings,
    write_narration_markdown,
)


def test_merged_settings_hints_and_segment_override(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    cfg_dict = {
        "segment_names": {"01": "01-demo"},
        "narration_from_source": {
            "hints": ["Global hint."],
            "context": {"paths": ["README.md"]},
            "segments": {
                "01": {
                    "hints": ["Segment hint."],
                    "context": {"paths": ["src/x.ts"]},
                }
            },
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg_dict), encoding="utf-8")
    (tmp_path / "README.md").write_text("r", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.ts").write_text("//x", encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    s = merged_narration_from_source_settings(cfg, "01")
    assert "Global hint." in s.hints and "Segment hint." in s.hints
    assert "README.md" in s.context_paths and "src/x.ts" in s.context_paths


def test_collect_source_snippets_respects_extra_paths(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump({"narration_from_source": {"context": {"paths": ["a.txt"]}}}),
        encoding="utf-8",
    )
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    s = merged_narration_from_source_settings(cfg, "01")
    snips = collect_source_snippets(cfg, s, extra_paths=["b.txt"], max_context_bytes=10_000)
    labels = {x[0] for x in snips}
    assert "a.txt" in labels and "b.txt" in labels


def test_build_owner_hints_guidance() -> None:
    from docgen.narrate_from_source import NarrationFromSourceSettings

    s = NarrationFromSourceSettings(
        model="x",
        temperature=0.5,
        max_context_bytes=100,
        system_prompt="sys",
        hints=["One"],
        context_paths=[],
        context_globs=[],
    )
    g = build_owner_hints_guidance(s, ["Two"])
    assert "- One" in g and "- Two" in g


def test_generate_narration_markdown_calls_openai(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump(
            {
                "segments": {"default": ["01"], "all": ["01"]},
                "segment_names": {"01": "01-demo"},
                "narration_from_source": {
                    "model": "gpt-4o-mini",
                    "context": {"paths": ["lib.py"]},
                    "hints": ["Keep it short."],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "lib.py").write_text("def f(): pass\n", encoding="utf-8")
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")

    with patch("docgen.wizard.generate_narration_via_llm") as m:
        m.return_value = "Paragraph one.\n\nParagraph two.\n"
        out = generate_narration_markdown(cfg, "01", extra_paths=[], extra_hints=[])
        assert out.strip().startswith("Paragraph")
        assert m.called
        call_kw = m.call_args.kwargs
        assert "- Keep it short." in call_kw.get("guidance", "")


def test_write_narration_markdown_creates_file(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump(
            {
                "dirs": {"narration": "narration"},
                "segments": {"default": ["01"], "all": ["01"]},
                "segment_names": {"01": "01-demo"},
            }
        ),
        encoding="utf-8",
    )
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    p = write_narration_markdown(cfg, "01", "Line.\n", force=False)
    assert p.read_text(encoding="utf-8").strip() == "Line."


def test_narration_generate_cli_dry_run(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    (tmp_path / ".git").mkdir()
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump(
            {
                "segments": {"default": ["01"], "all": ["01"]},
                "segment_names": {"01": "01-demo"},
                "narration_from_source": {"context": {"paths": ["x.md"]}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "x.md").write_text("# src\nbody", encoding="utf-8")
    runner = CliRunner()

    with patch("docgen.wizard.generate_narration_via_llm") as m:
        m.return_value = "CLI out.\n"
        r = runner.invoke(
            main,
            [
                "--config",
                str(tmp_path / "docgen.yaml"),
                "narration-generate",
                "--segment",
                "01",
                "--dry-run",
            ],
        )
    assert r.exit_code == 0, r.output
    assert "CLI out." in r.output
    assert not (tmp_path / "narration").exists() or not list((tmp_path / "narration").glob("*.md"))
