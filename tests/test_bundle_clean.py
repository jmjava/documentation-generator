"""bundle_clean helpers (no subprocess)."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.bundle_clean import clean_bundle_regenerable_outputs, remove_narration_markdown_except_readme
from docgen.config import Config


def _minimal_bundle(tmp_path: Path) -> Config:
    bundle = tmp_path / "demos"
    bundle.mkdir()
    (bundle / "docgen.yaml").write_text(
        yaml.dump(
            {
                "repo_root": ".",
                "dirs": {
                    "narration": "narration",
                    "audio": "audio",
                    "animations": "animations",
                    "terminal": "terminal",
                    "recordings": "recordings",
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".git").mkdir()
    narr = bundle / "narration"
    narr.mkdir()
    (narr / "README.md").write_text("x", encoding="utf-8")
    (narr / "01-a.md").write_text("n1", encoding="utf-8")
    (bundle / "audio").mkdir()
    (bundle / "audio" / "a.mp3").write_text("m", encoding="utf-8")
    (bundle / "animations").mkdir()
    (bundle / "animations" / "scenes.py").write_text("#x", encoding="utf-8")
    (bundle / "terminal").mkdir()
    (bundle / "terminal" / "x.tape").write_text("t", encoding="utf-8")
    (bundle / "recordings").mkdir()
    (bundle / "recordings" / "a.mp4").write_text("v", encoding="utf-8")
    (bundle / "recordings" / "per-function").mkdir()
    (bundle / "recordings" / "per-function" / "x.txt").write_text("p", encoding="utf-8")
    (bundle / ".docgen-state.json").write_text("{}", encoding="utf-8")
    return Config.from_yaml(bundle / "docgen.yaml")


def test_remove_narration_skips_readme(tmp_path: Path) -> None:
    d = tmp_path / "narration"
    d.mkdir()
    (d / "README.md").write_text("a")
    (d / "01-x.md").write_text("b")
    assert remove_narration_markdown_except_readme(d) == 1
    assert (d / "README.md").is_file()
    assert not (d / "01-x.md").exists()


def test_clean_bundle_wipes_and_keep_narration(tmp_path: Path) -> None:
    cfg = _minimal_bundle(tmp_path)
    s = clean_bundle_regenerable_outputs(cfg, keep_narration=True)
    assert s["narration_md_removed"] == 0
    assert (cfg.narration_dir / "01-a.md").is_file()
    assert not (cfg.audio_dir / "a.mp3").exists()
    assert (cfg.animations_dir).is_dir()
    assert not (cfg.animations_dir / "scenes.py").exists()
    assert (cfg.terminal_dir / "rendered").is_dir()
    assert not (cfg.terminal_dir / "x.tape").exists()
    assert not (cfg.recordings_dir / "a.mp4").exists()
    assert (cfg.recordings_dir / "per-function").is_dir()
    assert not (cfg.base_dir / ".docgen-state.json").exists()


def test_clean_bundle_removes_narration_by_default(tmp_path: Path) -> None:
    cfg = _minimal_bundle(tmp_path)
    clean_bundle_regenerable_outputs(cfg, keep_narration=False)
    assert not (cfg.narration_dir / "01-a.md").exists()
    assert (cfg.narration_dir / "README.md").is_file()


def test_clean_bundle_preserves_repo_fixtures_and_capture_scripts(tmp_path: Path) -> None:
    """Repo-root fixtures and hand-authored capture scripts survive clean-bundle.

    Category B (per `.cursor/rules/no-asset-edits.mdc`): repo-root ``fixtures/**``,
    ``docs/demos/scripts/*.py``, ``docs/demos/terminal/*.tape``,
    ``docs/demos/narration/README.md``.
    """
    cfg = _minimal_bundle(tmp_path)
    bundle = cfg.base_dir
    repo_root = tmp_path

    fx = repo_root / "fixtures" / "any-playwright-app"
    fx.mkdir(parents=True)
    (fx / "package.json").write_text('{"devDependencies": {"@playwright/test": "^1.0"}}', encoding="utf-8")
    (fx / "smoke.spec.ts").write_text("test('x', () => {});", encoding="utf-8")

    sc = bundle / "scripts"
    sc.mkdir()
    (sc / "segment_99_capture.py").write_text("# capture\n", encoding="utf-8")

    clean_bundle_regenerable_outputs(cfg, keep_narration=True)

    assert (fx / "package.json").is_file()
    assert (fx / "smoke.spec.ts").is_file()
    assert (sc / "segment_99_capture.py").is_file()


def test_clean_bundle_wipes_per_function_outputs(tmp_path: Path) -> None:
    """``per-function/*.{docgen.yaml,html}`` are now Category C (LLM-generated)
    and must be wiped so ``per-function-generate --force`` starts clean."""
    cfg = _minimal_bundle(tmp_path)
    pf = cfg.base_dir / "per-function"
    pf.mkdir()
    (pf / "lesson-x.docgen.yaml").write_text("kind: playwright\n", encoding="utf-8")
    (pf / "lesson-x.html").write_text("<html></html>", encoding="utf-8")

    summary = clean_bundle_regenerable_outputs(cfg, keep_narration=True)

    assert summary["per_function_outputs_removed"] == 2
    assert not (pf / "lesson-x.docgen.yaml").exists()
    assert not (pf / "lesson-x.html").exists()
    assert pf.is_dir()  # dir kept; only contents wiped
