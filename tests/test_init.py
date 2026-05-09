"""Tests for docgen.init — project scaffolding wizard."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.init import (
    InitPlan,
    build_defaults_plan,
    detect_git_root,
    detect_playwright_project_dirs,
    discover_default_discover_roots,
    generate_files,
    infer_segments_from_narrations,
    read_segments_file,
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
    assert (tmp_path / "demos" / "terminal" / "README.md").exists()
    assert (tmp_path / "demos" / "narration" / "01-intro.md").exists()
    assert (tmp_path / "demos" / "narration" / "02-setup.md").exists()

    cfg_text = (tmp_path / "demos" / "docgen.yaml").read_text()
    cfg = yaml.safe_load(cfg_text.split("\n\n", 1)[-1])
    assert cfg["segments"]["all"] == ["01", "02"]
    assert cfg["segment_names"]["01"] == "01-intro"
    assert "manim" not in cfg
    assert cfg["vhs"]["render_timeout_sec"] == 120
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


# Generic Playwright detection (no fixture name is hardcoded into init).


def test_detect_playwright_project_dirs_via_package_json(tmp_path: Path) -> None:
    proj = tmp_path / "fixtures" / "any-name-here"
    proj.mkdir(parents=True)
    (proj / "package.json").write_text(
        '{"name": "x", "devDependencies": {"@playwright/test": "^1.0"}}',
        encoding="utf-8",
    )
    found = detect_playwright_project_dirs(tmp_path)
    assert found == [proj.resolve()]


def test_detect_playwright_project_dirs_via_config_file(tmp_path: Path) -> None:
    proj = tmp_path / "e2e"
    proj.mkdir()
    (proj / "playwright.config.ts").write_text("export default {};", encoding="utf-8")
    assert detect_playwright_project_dirs(tmp_path) == [proj.resolve()]


def test_detect_playwright_project_dirs_skips_node_modules(tmp_path: Path) -> None:
    nm = tmp_path / "node_modules" / "@playwright" / "test"
    nm.mkdir(parents=True)
    (nm / "package.json").write_text(
        '{"name": "@playwright/test"}', encoding="utf-8"
    )
    assert detect_playwright_project_dirs(tmp_path) == []


def test_detect_playwright_project_dirs_no_signal(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    assert detect_playwright_project_dirs(tmp_path) == []


def test_discover_default_discover_roots_with_playwright(tmp_path: Path) -> None:
    demo = tmp_path / "docs" / "demos"
    demo.mkdir(parents=True)
    proj = tmp_path / "apps" / "frontend"
    proj.mkdir(parents=True)
    (proj / "package.json").write_text(
        '{"devDependencies": {"playwright": "^1.0"}}', encoding="utf-8"
    )
    roots = discover_default_discover_roots(tmp_path, demo)
    assert roots[0] == "."
    assert "../../apps/frontend" in roots


def test_discover_default_discover_roots_blank_repo(tmp_path: Path) -> None:
    demo = tmp_path / "docs" / "demos"
    demo.mkdir(parents=True)
    assert discover_default_discover_roots(tmp_path, demo) == ["."]


def test_build_defaults_plan_no_bundle_no_fixture(tmp_path: Path, monkeypatch) -> None:
    """Greenfield: build_defaults_plan never references a hardcoded fixture path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    plan = build_defaults_plan(target_dir=None)
    assert plan.discover_roots == ["."]
    assert plan.segments == [{"id": "01", "name": "01-intro"}]


def test_build_defaults_plan_detects_playwright_signal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    proj = tmp_path / "fixtures" / "any-fixture"
    proj.mkdir(parents=True)
    (proj / "package.json").write_text(
        '{"devDependencies": {"@playwright/test": "^1.0"}}', encoding="utf-8"
    )
    plan = build_defaults_plan(target_dir=None)
    assert "../../fixtures/any-fixture" in plan.discover_roots


def test_read_segments_file_basic(tmp_path: Path) -> None:
    f = tmp_path / "segments.txt"
    f.write_text(
        "# leading comment\n"
        "01-overview\n"
        "02-init-scaffold\n"
        "\n"
        "03-wizard-gui\n",
        encoding="utf-8",
    )
    segs = read_segments_file(f)
    assert segs == [
        {"id": "01", "name": "01-overview"},
        {"id": "02", "name": "02-init-scaffold"},
        {"id": "03", "name": "03-wizard-gui"},
    ]


def test_read_segments_file_dedupes_and_assigns_id_when_missing(tmp_path: Path) -> None:
    f = tmp_path / "segments.txt"
    f.write_text(
        "intro\n"
        "intro\n"
        "deep-dive\n",
        encoding="utf-8",
    )
    segs = read_segments_file(f)
    assert segs == [
        {"id": "01", "name": "intro"},
        {"id": "02", "name": "deep-dive"},
    ]


def test_build_defaults_plan_segments_file_overrides_narration_scan(
    tmp_path: Path, monkeypatch
) -> None:
    """A segments file is the authoritative source even when narration/*.md still exists."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    demo = tmp_path / "docs" / "demos"
    (demo / "narration").mkdir(parents=True)
    (demo / "narration" / "99-stale.md").write_text("stale", encoding="utf-8")

    seg_file = tmp_path / "segments.txt"
    seg_file.write_text("01-overview\n02-init-scaffold\n", encoding="utf-8")

    plan = build_defaults_plan(target_dir=None, segments_file=seg_file)
    assert plan.segments == [
        {"id": "01", "name": "01-overview"},
        {"id": "02", "name": "02-init-scaffold"},
    ]


def test_build_defaults_plan_segments_file_empty_falls_back_to_starter(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    seg_file = tmp_path / "segments.txt"
    seg_file.write_text("# only comments\n\n", encoding="utf-8")

    plan = build_defaults_plan(target_dir=None, segments_file=seg_file)
    assert plan.segments == [{"id": "01", "name": "01-intro"}]
