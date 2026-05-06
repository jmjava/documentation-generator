"""Discover Playwright tests in a host repository (Node / ``@playwright/test`` first)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLAYWRIGHT_CONFIG_NAMES = (
    "playwright.config.ts",
    "playwright.config.js",
    "playwright.config.mjs",
    "playwright.config.cjs",
)


@dataclass(frozen=True)
class NodePlaywrightTest:
    """One discovered test from ``playwright test --list``."""

    spec_path: str  # relative to repo root, POSIX-style
    line: int | None
    title: str
    project: str | None

    def stable_id(self) -> str:
        raw = f"{self.spec_path}\0{self.title}"
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"pw-{h}"

    def suggested_visual_map_snippet(self, segment_key: str) -> str:
        """YAML snippet for ``visual_map`` (``playwright_test`` style)."""
        tid = f"{self.spec_path}::{self.title}"
        return (
            f'  "{segment_key}":\n'
            f'    type: playwright_test\n'
            f'    test: "{tid}"\n'
            f'    source: ""  # set after first run (e.g. test-results/...webm)\n'
        )

    def catalog_entry(self) -> dict[str, Any]:
        """Entry dict for ``docgen.catalog.yaml`` / :func:`source_catalog.merge_entries`."""
        return {
            "id": self.stable_id(),
            "kind": "playwright_node",
            "test": {"spec": self.spec_path, "title": self.title, "project": self.project},
            "fingerprints": {"tracked_paths": [self.spec_path], "inputs": {}},
        }


def find_playwright_config(repo_root: Path) -> Path | None:
    for name in PLAYWRIGHT_CONFIG_NAMES:
        p = repo_root / name
        if p.is_file():
            return p
    return None


def package_json_path(repo_root: Path) -> Path | None:
    p = repo_root / "package.json"
    return p if p.is_file() else None


def node_playwright_dependency_present(repo_root: Path) -> bool:
    pj = package_json_path(repo_root)
    if not pj:
        return False
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    deps = data.get("dependencies") or {}
    dev = data.get("devDependencies") or {}
    for d in (deps, dev):
        if isinstance(d, dict) and "@playwright/test" in d:
            return True
    return False


def node_playwright_project_ready(repo_root: Path) -> bool:
    """True if repo looks like a Node Playwright test project."""
    return find_playwright_config(repo_root) is not None and node_playwright_dependency_present(
        repo_root
    )


#: ``playwright test --list`` line: ``  [chromium] › spec.ts:10:5 › title``
_LIST_LINE = re.compile(
    r"^\s*\[(?P<project>[^\]]+)\]\s*›\s*(?P<file>\S+):(?P<line>\d+):(?P<col>\d+)\s*›\s*(?P<title>.+?)\s*$"
)


def parse_playwright_list_text(stdout: str) -> list[NodePlaywrightTest]:
    """Parse default ``--list`` reporter output (no JSON)."""
    found: list[NodePlaywrightTest] = []
    seen: set[tuple[str, str]] = set()
    for line in stdout.splitlines():
        m = _LIST_LINE.match(line)
        if not m:
            continue
        spec = m.group("file").replace("\\", "/")
        title = m.group("title").strip()
        key = (spec, title)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            NodePlaywrightTest(
                spec_path=spec,
                line=int(m.group("line")),
                title=title,
                project=m.group("project").strip(),
            )
        )
    return found


def parse_playwright_list_json(blob: str) -> list[NodePlaywrightTest]:
    """Parse JSON blob if ``--reporter=json`` wrote a root object with suites."""
    found: list[NodePlaywrightTest] = []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []

    def walk_suite(suite: dict[str, Any], default_file: str = "") -> None:
        suite_file = suite.get("file") or default_file
        if isinstance(suite_file, str):
            suite_file = suite_file.replace("\\", "/")
        for spec in suite.get("specs") or []:
            if not isinstance(spec, dict):
                continue
            sp_file = spec.get("file") or suite_file
            if not isinstance(sp_file, str):
                continue
            sp_file = sp_file.replace("\\", "/")
            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                title = str(test.get("title") or spec.get("title") or "").strip()
                if not title:
                    continue
                line = test.get("line")
                found.append(
                    NodePlaywrightTest(
                        spec_path=sp_file,
                        line=int(line) if line is not None else None,
                        title=title,
                        project=None,
                    )
                )
        for child in suite.get("suites") or []:
            if isinstance(child, dict):
                walk_suite(child, suite_file if isinstance(suite_file, str) else default_file)

    for suite in data.get("suites") or []:
        if isinstance(suite, dict):
            walk_suite(suite)
    # de-dupe
    uniq: dict[tuple[str, str], NodePlaywrightTest] = {}
    for t in found:
        uniq[(t.spec_path, t.title)] = t
    return list(uniq.values())


def _extract_json_object(text: str) -> str | None:
    """If *text* contains a JSON object, return the substring from first ``{`` to last ``}``."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    return text[start : end + 1]


def discover_node_playwright_tests(
    repo_root: Path,
    *,
    playwright_config: Path | None = None,
    timeout_sec: int = 300,
) -> list[NodePlaywrightTest]:
    """Run ``npx playwright test --list`` under *repo_root* and parse tests."""
    rr = repo_root.resolve()
    if not node_playwright_project_ready(rr):
        return []

    cmd = ["npx", "playwright", "test", "--list", "--reporter=json"]
    cfg = playwright_config or find_playwright_config(rr)
    if cfg is not None:
        rel = cfg.name
        if cfg.parent.resolve() == rr:
            cmd.extend(["--config", rel])
        else:
            cmd.extend(["--config", str(cfg.resolve())])

    env = os.environ.copy()
    env.setdefault("CI", "1")
    try:
        proc = subprocess.run(
            cmd,
            cwd=rr,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    blob = _extract_json_object(combined.strip())
    if blob:
        parsed = parse_playwright_list_json(blob)
        if parsed:
            return parsed
    return parse_playwright_list_text(combined)


def parse_playwright_config_insights(config_path: Path) -> dict[str, Any]:
    """Best-effort extract of common fields from ``playwright.config.{ts,js,...}``.

    Used for docs / wizard / LLM context (not a full TypeScript parser). Keys may be
    missing: ``base_url``, ``web_server_url``, ``video``, ``trace``, ``output_dir``.
    """
    out: dict[str, Any] = {}
    if not config_path.is_file():
        return out
    text = config_path.read_text(encoding="utf-8", errors="replace")

    def _quoted(attr: str) -> re.Match[str] | None:
        return re.search(rf"{attr}\s*:\s*['\"]([^'\"]+)['\"]", text)

    m = _quoted("baseURL")
    if m:
        out["base_url"] = m.group(1).strip()
    m = re.search(
        r"url\s*:\s*['\"]([^'\"]+)['\"]",
        text,
    )
    if m and "webServer" in text:
        out["web_server_url"] = m.group(1).strip()
    m = re.search(r"video\s*:\s*['\"]([^'\"]+)['\"]", text)
    if m:
        out["video"] = m.group(1).strip()
    m = re.search(r"trace\s*:\s*['\"]([^'\"]+)['\"]", text)
    if m:
        out["trace"] = m.group(1).strip()
    m = re.search(r"outputDir\s*:\s*['\"]([^'\"]+)['\"]", text)
    if m:
        out["output_dir"] = m.group(1).strip()
    return out


def _normalize_spec_to_repo(repo_root: Path, scan_root: Path, spec: str) -> str:
    """Make spec path relative to *repo_root* when *scan_root* is a subdir."""
    rr = repo_root.resolve()
    sr = scan_root.resolve()
    p = Path(spec)
    if p.is_absolute():
        try:
            return str(p.resolve().relative_to(rr)).replace("\\", "/")
        except ValueError:
            return spec.replace("\\", "/")
    joined = (sr / p).resolve()
    try:
        return str(joined.relative_to(rr)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def discover_all_node_playwright_tests(repo_root: Path, scan_roots: list[Path]) -> list[NodePlaywrightTest]:
    """Discover from each scan root; de-dupe by (spec relative to *repo_root*, title)."""
    rr = repo_root.resolve()
    uniq: dict[tuple[str, str], NodePlaywrightTest] = {}
    for root in scan_roots:
        root = root.resolve()
        if not node_playwright_project_ready(root):
            continue
        for t in discover_node_playwright_tests(root):
            spec = _normalize_spec_to_repo(rr, root, t.spec_path)
            key = (spec, t.title)
            uniq[key] = NodePlaywrightTest(
                spec_path=spec,
                line=t.line,
                title=t.title,
                project=t.project,
            )
    return list(uniq.values())


def format_suggested_visual_map_yaml(
    tests: list[NodePlaywrightTest],
    *,
    segment_key_start: str = "90",
) -> str:
    """Emit a ``visual_map`` YAML block with ``playwright_test`` entries (keys auto-increment)."""
    try:
        n = int(str(segment_key_start).strip())
    except ValueError:
        n = 90
    lines = [
        "# Suggested visual_map entries (playwright_test). Adjust keys and `source` after first run.",
        "visual_map:",
    ]
    for t in tests:
        key = str(n).zfill(2)
        lines.append(t.suggested_visual_map_snippet(key).rstrip())
        n += 1
    return "\n".join(lines) + "\n"


def discover_tests_yaml_lines(tests: list[NodePlaywrightTest]) -> str:
    """Human-readable YAML-ish listing for stdout."""
    if not tests:
        return "# Discovered @playwright/test entries\n# (none)\n"
    lines = ["# Discovered @playwright/test entries", "tests:"]
    for t in tests:
        lines.append(f'  - spec: "{t.spec_path}"')
        lines.append(f'    title: "{t.title.replace(chr(34), chr(39))}"')
        if t.project:
            lines.append(f'    project: "{t.project}"')
        lines.append(f'    id: {t.stable_id()}')
    return "\n".join(lines) + "\n"
