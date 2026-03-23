"""Tests for docgen.init — project scaffolding wizard."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.init import (
    InitPlan,
    detect_git_root,
    generate_files,
    infer_segments_from_narrations,
    scan_existing_assets,
    scan_narrations,
)


def test_detect_git_root(tmp_path: Path) -> None:
    git_dir = tmp_path / "repo" / ".git"
    git_dir.mkdir(parents=True)
    sub = tmp_path / "repo" / "a" / "b"
    sub.mkdir(parents=True)
    assert detect_git_root(sub) == tmp_path / "repo"


def test_detect_git_root_none(tmp_path: Path) -> None:
    sub = tmp_path / "no-repo" / "a"
    sub.mkdir(parents=True)
    assert detect_git_root(sub) is None


def test_scan_narrations(tmp_path: Path) -> None:
    narr = tmp_path / "narration"
    narr.mkdir()
    (narr / "01-intro.md").write_text("Hello")
    (narr / "02-setup.md").write_text("World")
    (narr / "README.md").write_text("Docs")
    files = scan_narrations(tmp_path)
    assert len(files) == 2
    assert files[0].name == "01-intro.md"


def test_scan_narrations_empty(tmp_path: Path) -> None:
    assert scan_narrations(tmp_path) == []


def test_infer_segments(tmp_path: Path) -> None:
    files = [
        tmp_path / "01-intro.md",
        tmp_path / "02-setup.md",
        tmp_path / "03-walkthrough.md",
    ]
    segments = infer_segments_from_narrations(files)
    assert len(segments) == 3
    assert segments[0] == {"id": "01", "name": "01-intro"}
    assert segments[2] == {"id": "03", "name": "03-walkthrough"}


def test_scan_existing_assets(tmp_path: Path) -> None:
    (tmp_path / "narration").mkdir()
    (tmp_path / "narration" / "01.md").write_text("x")
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "01.mp3").write_text("x")
    (tmp_path / "audio" / "02.mp3").write_text("x")
    counts = scan_existing_assets(tmp_path)
    assert counts["narration"] == 1
    assert counts["audio"] == 2
    assert "recordings" not in counts


def test_generate_files_minimal(tmp_path: Path) -> None:
    plan = InitPlan(
        project_name="test-project",
        demo_dir=tmp_path / "demos",
        repo_root=tmp_path,
        segments=[
            {"id": "01", "name": "01-intro"},
            {"id": "02", "name": "02-setup"},
        ],
    )
    created = generate_files(plan)

    assert (tmp_path / "demos" / "docgen.yaml").exists()
    assert (tmp_path / "demos" / "generate-all.sh").exists()
    assert (tmp_path / "demos" / "compose.sh").exists()
    assert (tmp_path / "demos" / "rebuild-after-audio.sh").exists()
    assert (tmp_path / "demos" / "validate.sh").exists()
    assert (tmp_path / "demos" / "narration" / "README.md").exists()
    assert (tmp_path / "demos" / "narration" / "01-intro.md").exists()
    assert (tmp_path / "demos" / "narration" / "02-setup.md").exists()

    cfg_text = (tmp_path / "demos" / "docgen.yaml").read_text()
    cfg = yaml.safe_load(cfg_text.split("\n\n", 1)[-1])
    assert cfg["segments"]["all"] == ["01", "02"]
    assert cfg["segment_names"]["01"] == "01-intro"
    assert "test-project" in cfg["tts"]["instructions"]

    assert len(created) >= 7


def test_generate_files_preserves_existing_narration(tmp_path: Path) -> None:
    demo = tmp_path / "demos"
    narr = demo / "narration"
    narr.mkdir(parents=True)
    (narr / "01-intro.md").write_text("My custom narration.")

    plan = InitPlan(
        project_name="test",
        demo_dir=demo,
        repo_root=tmp_path,
        segments=[{"id": "01", "name": "01-intro"}],
    )
    generate_files(plan)

    assert (narr / "01-intro.md").read_text() == "My custom narration."


def test_generate_files_scripts_executable(tmp_path: Path) -> None:
    plan = InitPlan(
        project_name="test",
        demo_dir=tmp_path / "demos",
        repo_root=tmp_path,
        segments=[{"id": "01", "name": "01-intro"}],
    )
    generate_files(plan)
    for script in ["generate-all.sh", "compose.sh", "rebuild-after-audio.sh", "validate.sh"]:
        path = tmp_path / "demos" / script
        assert path.stat().st_mode & 0o111, f"{script} should be executable"


def test_generate_files_with_env_file(tmp_path: Path) -> None:
    plan = InitPlan(
        project_name="test",
        demo_dir=tmp_path / "demos",
        repo_root=tmp_path,
        segments=[{"id": "01", "name": "01-intro"}],
        env_file_rel="../../.env",
    )
    generate_files(plan)

    cfg_text = (tmp_path / "demos" / "docgen.yaml").read_text()
    cfg = yaml.safe_load(cfg_text.split("\n\n", 1)[-1])
    assert cfg["env_file"] == "../../.env"


def test_generate_files_creates_directories(tmp_path: Path) -> None:
    plan = InitPlan(
        project_name="test",
        demo_dir=tmp_path / "demos",
        repo_root=tmp_path,
        segments=[{"id": "01", "name": "01-intro"}],
    )
    generate_files(plan)

    for subdir in ["narration", "audio", "animations", "terminal", "terminal/rendered", "recordings"]:
        assert (tmp_path / "demos" / subdir).is_dir()


def test_generate_files_pre_push_hook(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    plan = InitPlan(
        project_name="test",
        demo_dir=tmp_path / "demos",
        repo_root=tmp_path,
        segments=[{"id": "01", "name": "01-intro"}],
        install_pre_push=True,
    )
    generate_files(plan)

    precommit = tmp_path / ".pre-commit-config.yaml"
    assert precommit.exists()
    content = precommit.read_text()
    assert "docgen-validate" in content
    assert "demos" in content
