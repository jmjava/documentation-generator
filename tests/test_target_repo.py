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
    assert repo_cache_name("https://github.com/acme/app.git") == "acme-app"
    assert repo_cache_name("https://github.com/other/app.git") == "other-app"
    assert repo_cache_name("git@github.com:acme/app.git") == "acme-app"


def test_resolve_repo_local_path(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    assert resolve_repo(str(tmp_path)) == tmp_path.resolve()


def test_resolve_repo_missing_local_raises(tmp_path: Path) -> None:
    with pytest.raises(TargetRepoError, match="does not exist"):
        resolve_repo(str(tmp_path / "nope"))


def test_resolve_repo_reuses_existing_clone(tmp_path: Path) -> None:
    dest = tmp_path / "cache" / "acme-app"
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
    assert out == (cache / "acme-app").resolve()
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


def test_find_bundle_yaml_skips_vendor_and_recordings(tmp_path: Path) -> None:
    junk = tmp_path / "node_modules" / "pkg" / "docgen.yaml"
    junk.parent.mkdir(parents=True)
    junk.write_text("nope: true\n", encoding="utf-8")
    rec = tmp_path / "docs" / "demos" / "recordings" / "docgen.yaml"
    rec.parent.mkdir(parents=True)
    rec.write_text("nope: true\n", encoding="utf-8")
    real = tmp_path / "docs" / "demos" / "nested" / "docgen.yaml"
    real.parent.mkdir(parents=True)
    real.write_text("ok: true\n", encoding="utf-8")
    assert find_bundle_yaml(tmp_path) == real


def test_find_bundle_yaml_prefers_demos_dir(tmp_path: Path) -> None:
    (tmp_path / "demos").mkdir()
    demos = tmp_path / "demos" / "docgen.yaml"
    demos.write_text("segments: {}\n", encoding="utf-8")
    (tmp_path / "docgen.yaml").write_text("wrong: true\n", encoding="utf-8")
    assert find_bundle_yaml(tmp_path) == demos


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


def test_clone_git_repo_keeps_github_token_off_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from docgen.target_repo import clone_git_repo

    captured: dict = {}

    def _run(cmd, **kwargs):  # noqa: ANN003
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret_token")
    with patch("docgen.target_repo.subprocess.run", side_effect=_run):
        clone_git_repo("https://github.com/acme/app.git", tmp_path / "app")
    joined = " ".join(captured["cmd"])
    assert "ghs_secret_token" not in joined
    assert captured["env"]["GIT_CONFIG_VALUE_0"] == "https://github.com/"
    assert "ghs_secret_token" in captured["env"]["GIT_CONFIG_KEY_0"]


def test_clone_git_repo_preserves_existing_git_config_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from docgen.target_repo import clone_git_repo

    captured: dict = {}

    def _run(cmd, **kwargs):  # noqa: ANN003
        captured["cmd"] = list(cmd)
        captured["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret_token")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "bot")
    with patch("docgen.target_repo.subprocess.run", side_effect=_run):
        clone_git_repo("https://github.com/acme/app.git", tmp_path / "app")
    env = captured["env"]
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "user.name"
    assert env["GIT_CONFIG_VALUE_0"] == "bot"
    assert "ghs_secret_token" in env["GIT_CONFIG_KEY_1"]
    assert env["GIT_CONFIG_VALUE_1"] == "https://github.com/"
    assert "ghs_secret_token" not in " ".join(captured["cmd"])


def test_missing_nested_path_is_not_github_shorthand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)
    with patch("docgen.target_repo.clone_git_repo") as clone:
        with pytest.raises(TargetRepoError, match="does not exist"):
            resolve_repo("docs/demos")
        clone.assert_not_called()


def test_cached_clone_resets_working_tree_to_fetch_head(tmp_path: Path) -> None:
    import subprocess

    dest = tmp_path / "cache" / "acme-app"
    dest.mkdir(parents=True)
    (dest / ".git").mkdir()
    cmds: list[list[str]] = []

    def _run(cmd, **kwargs):  # noqa: ANN003
        cmds.append(list(cmd))
        if "get-url" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/acme/app.git\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch("docgen.target_repo.subprocess.run", side_effect=_run):
        out = resolve_repo("https://github.com/acme/app.git", cache_dir=tmp_path / "cache")
    assert out == dest.resolve()
    assert any("fetch" in c for c in cmds)
    assert any("FETCH_HEAD" in c for c in cmds)


def test_cached_clone_rejects_different_origin(tmp_path: Path) -> None:
    import subprocess

    dest = tmp_path / "cache" / "acme-app"
    dest.mkdir(parents=True)
    (dest / ".git").mkdir()

    def _run(cmd, **kwargs):  # noqa: ANN003
        if "get-url" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, "https://github.com/other/app.git\n", ""
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch("docgen.target_repo.subprocess.run", side_effect=_run):
        with pytest.raises(TargetRepoError, match="is origin"):
            resolve_repo("https://github.com/acme/app.git", cache_dir=tmp_path / "cache")
