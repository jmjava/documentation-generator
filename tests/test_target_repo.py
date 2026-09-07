"""Tests for :mod:`docgen.target_repo` and ``docgen --repo``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from docgen.cli import main
from docgen.init import build_defaults_plan
from docgen.target_repo import (
    TargetRepoError,
    find_bundle_yaml,
    looks_like_git_url,
    normalize_git_url,
    repo_cache_name,
    resolve_repo,
)


def test_looks_like_git_url() -> None:
    assert looks_like_git_url("https://github.com/acme/app.git")
    assert looks_like_git_url("git@github.com:acme/app.git")
    assert looks_like_git_url("github.com/acme/app")
    assert looks_like_git_url("acme/app")
    assert not looks_like_git_url("/tmp/local-checkout")
    assert not looks_like_git_url("")


def test_normalize_git_url() -> None:
    assert normalize_git_url("acme/app") == "https://github.com/acme/app.git"
    assert normalize_git_url("github.com/acme/app") == "https://github.com/acme/app.git"
    assert (
        normalize_git_url("https://github.com/acme/app")
        == "https://github.com/acme/app.git"
    )


def test_repo_cache_name() -> None:
    assert repo_cache_name("https://github.com/acme/app.git") == "app"


def test_resolve_repo_local_path(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    assert resolve_repo(str(tmp_path)) == tmp_path.resolve()


def test_resolve_repo_missing_local_raises(tmp_path: Path) -> None:
    with pytest.raises(TargetRepoError, match="does not exist"):
        resolve_repo(str(tmp_path / "nope"))


def test_resolve_repo_reuses_existing_clone(tmp_path: Path) -> None:
    dest = tmp_path / "cache" / "app"
    dest.mkdir(parents=True)
    (dest / ".git").mkdir()
    out = resolve_repo("https://github.com/acme/app.git", cache_dir=tmp_path / "cache")
    assert out == dest.resolve()


def test_resolve_repo_clones_when_missing(tmp_path: Path) -> None:
    cache = tmp_path / "cache"

    def _fake_clone(url: str, dest: Path) -> None:
        dest.mkdir(parents=True)
        (dest / ".git").mkdir()
        (dest / "README.md").write_text(url, encoding="utf-8")

    with patch("docgen.target_repo.clone_git_repo", side_effect=_fake_clone):
        out = resolve_repo("acme/app", cache_dir=cache)
    assert out == (cache / "app").resolve()
    assert (out / "README.md").read_text(encoding="utf-8").endswith("acme/app.git")


def test_find_bundle_yaml_prefers_docs_demos(tmp_path: Path) -> None:
    (tmp_path / "docs" / "demos").mkdir(parents=True)
    canonical = tmp_path / "docs" / "demos" / "docgen.yaml"
    canonical.write_text("segments: {}\n", encoding="utf-8")
    (tmp_path / "docgen.yaml").write_text("wrong: true\n", encoding="utf-8")
    assert find_bundle_yaml(tmp_path) == canonical


def test_find_bundle_yaml_skips_venv(tmp_path: Path) -> None:
    nested = tmp_path / ".venv" / "lib" / "docgen.yaml"
    nested.parent.mkdir(parents=True)
    nested.write_text("nope: true\n", encoding="utf-8")
    assert find_bundle_yaml(tmp_path) is None


def test_build_defaults_plan_repo_root_does_not_use_cwd_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--repo`` must scaffold the *consumer*, not this library's checkout."""
    library = tmp_path / "documentation-generator"
    consumer = tmp_path / "course-builder"
    library.mkdir()
    (library / ".git").mkdir()
    consumer.mkdir()
    (consumer / ".git").mkdir()
    monkeypatch.chdir(library)
    plan = build_defaults_plan(target_dir=None, repo_root=consumer)
    assert plan.repo_root == consumer.resolve()
    assert plan.demo_dir == (consumer / "docs" / "demos").resolve()


def _consumer_bundle(root: Path) -> Path:
    (root / ".git").mkdir()
    bundle = root / "docs" / "demos"
    bundle.mkdir(parents=True)
    (bundle / "narration").mkdir()
    (bundle / "narration" / "01-intro.md").write_text("Hello there.\n", encoding="utf-8")
    raw = {
        "repo_root": "../..",
        "dirs": {"narration": "narration"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-intro"},
        "visual_map": {"01": {"type": "still", "source": "01.mp4"}},
    }
    (bundle / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    return bundle


def test_cli_repo_runs_against_consumer_without_config_flag(tmp_path: Path) -> None:
    consumer = tmp_path / "app"
    consumer.mkdir()
    _consumer_bundle(consumer)
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(consumer), "lint", "--segment", "01"])
    assert result.exit_code == 0, result.output
    assert "target repo" in result.output
    assert "bundle:" in result.output
    assert str(consumer / "src") not in result.output


def test_cli_repo_init_defaults_writes_bundle_only(tmp_path: Path) -> None:
    consumer = tmp_path / "app"
    consumer.mkdir()
    (consumer / ".git").mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(consumer), "init", "--defaults"])
    assert result.exit_code == 0, result.output
    yaml_path = consumer / "docs" / "demos" / "docgen.yaml"
    assert yaml_path.is_file()
    assert not (consumer / "src").exists()
    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8").split("\n\n", 1)[-1])
    assert cfg["repo_root"] in ("../..", "..\\..")
    assert cfg["ai"]["provider"] == "openai"
    assert (consumer / "docs" / "demos" / "requirements-docgen.txt").is_file()
