"""test_discovery — Node Playwright list parsing."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from docgen import test_discovery as td
from docgen.test_discovery import (
    NodePlaywrightTest,
    discover_tests_yaml_lines,
    find_playwright_config,
    format_suggested_visual_map_yaml,
    node_playwright_dependency_present,
    node_playwright_project_ready,
    parse_playwright_config_insights,
    parse_playwright_list_json,
    parse_playwright_list_text,
)


def test_parse_playwright_list_text() -> None:
    raw = """
Listing tests:
  [chromium] › tests/e2e/login.spec.ts:12:7 › user can log in
  [firefox] › tests/e2e/login.spec.ts:12:7 › user can log in
  [chromium] › tests/e2e/other.spec.ts:3:5 › loads page
"""
    items = parse_playwright_list_text(raw)
    titles = {(t.spec_path, t.title) for t in items}
    assert ("tests/e2e/login.spec.ts", "user can log in") in titles
    assert ("tests/e2e/other.spec.ts", "loads page") in titles


def test_parse_playwright_list_json_minimal() -> None:
    blob = {
        "suites": [
            {
                "file": "tests/a.spec.ts",
                "specs": [
                    {
                        "title": "first",
                        "file": "tests/a.spec.ts",
                        "tests": [{"title": "first", "line": 4}],
                    }
                ],
            }
        ]
    }
    items = parse_playwright_list_json(json.dumps(blob))
    assert len(items) == 1
    assert items[0].spec_path == "tests/a.spec.ts"
    assert items[0].title == "first"


def test_node_playwright_project_ready(tmp_path: Path) -> None:
    (tmp_path / "playwright.config.ts").write_text("export default {}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.49.0"}}),
        encoding="utf-8",
    )
    assert node_playwright_project_ready(tmp_path) is True
    assert find_playwright_config(tmp_path) is not None
    assert node_playwright_dependency_present(tmp_path) is True


def test_stable_id_stable() -> None:
    a = NodePlaywrightTest("a.spec.ts", 1, "T", "chromium")
    b = NodePlaywrightTest("a.spec.ts", 2, "T", "firefox")
    assert a.stable_id() == b.stable_id()


def test_discover_tests_json_stdout_is_pure_when_no_tests(tmp_path: Path) -> None:
    """Machine-readable formats must not prefix stderr warnings on stdout (breaks ``| jq``)."""
    from click.testing import CliRunner
    from unittest.mock import patch

    from docgen.cli import main

    import json

    (tmp_path / ".git").mkdir()
    (tmp_path / "playwright.config.ts").write_text("export default {}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.0.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump({"segments": {"default": ["01"], "all": ["01"]}}),
        encoding="utf-8",
    )

    runner = CliRunner()
    with patch("docgen.test_discovery.discover_all_node_playwright_tests", return_value=[]):
        r = runner.invoke(
            main,
            [
                "--config",
                str(tmp_path / "docgen.yaml"),
                "discover-tests",
                "--repo-root",
                str(tmp_path),
                "--format=json",
            ],
        )
    assert r.exit_code == 0, r.stdout + r.stderr
    parsed = json.loads(r.stdout.strip())
    assert parsed == []
    assert r.stderr is not None
    assert "no tests parsed" in r.stderr


def test_discover_tests_merge_catalog_cli(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from unittest.mock import patch

    from docgen.cli import main

    (tmp_path / ".git").mkdir()
    (tmp_path / "playwright.config.ts").write_text("export default {}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.0.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump({"segments": {"default": ["01"], "all": ["01"]}}),
        encoding="utf-8",
    )
    fake = NodePlaywrightTest("t.spec.ts", 1, "One", "chromium")

    runner = CliRunner()
    with patch("docgen.test_discovery.discover_node_playwright_tests", return_value=[fake]):
        r = runner.invoke(
            main,
            [
                "--config",
                str(tmp_path / "docgen.yaml"),
                "discover-tests",
                "--repo-root",
                str(tmp_path),
                "--merge-catalog",
            ],
        )
    assert r.exit_code == 0, r.output
    cat = tmp_path / "docgen.catalog.yaml"
    assert cat.is_file()
    data = yaml.safe_load(cat.read_text(encoding="utf-8"))
    assert any(e.get("id") == fake.stable_id() for e in data.get("entries", []))


def test_discover_tests_yaml_empty() -> None:
    assert "none" in discover_tests_yaml_lines([]).lower()


def test_parse_playwright_config_insights(tmp_path: Path) -> None:
    p = tmp_path / "playwright.config.ts"
    p.write_text(
        "export default { use: { baseURL: 'http://127.0.0.1:3000' }, "
        "webServer: { url: 'http://127.0.0.1:3000' }, video: 'on', trace: 'on', outputDir: 'out' }",
        encoding="utf-8",
    )
    ins = parse_playwright_config_insights(p)
    assert ins.get("base_url") == "http://127.0.0.1:3000"
    assert ins.get("web_server_url") == "http://127.0.0.1:3000"
    assert ins.get("video") == "on"
    assert ins.get("trace") == "on"
    assert ins.get("output_dir") == "out"


def test_normalize_spec_to_repo(tmp_path: Path) -> None:
    rr = tmp_path.resolve()
    sub = tmp_path / "apps" / "web"
    sub.mkdir(parents=True)
    assert td._normalize_spec_to_repo(rr, rr, "e2e/a.spec.ts") == "e2e/a.spec.ts"
    assert td._normalize_spec_to_repo(rr, sub, "tests/foo.spec.ts") == "apps/web/tests/foo.spec.ts"


def test_format_suggested_visual_map_yaml() -> None:
    tests = [
        NodePlaywrightTest("a.spec.ts", 1, "first", "chromium"),
        NodePlaywrightTest("b.spec.ts", 2, "second", "chromium"),
    ]
    y = format_suggested_visual_map_yaml(tests, segment_key_start="03")
    assert '"03"' in y
    assert '"04"' in y
    assert "playwright_test" in y
    assert "a.spec.ts::first" in y
