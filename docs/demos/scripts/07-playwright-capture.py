#!/usr/bin/env python3
"""Generic Playwright capture driver invoked by ``docgen compose``.

Picked up automatically by ``visual_map`` discovery (``yaml-generate``) for any
segment whose id appears in this filename — here, segment ``07``. The script is
intentionally fixture-agnostic:

1. It locates a Playwright project under the repo by signal, not by name —
   ``package.json`` listing ``@playwright/test`` / ``playwright`` /
   ``playwright-core``, or a ``playwright.config.{js,ts,mjs,cjs}``. Override
   with ``DOCGEN_PLAYWRIGHT_FIXTURE_DIR`` (absolute path or relative to repo root).
2. It boots ``npm run dev`` in that project on a free port (unless
   ``DOCGEN_PLAYWRIGHT_URL`` points at an already-running server).
3. It records Chromium with Playwright's video API and writes the file expected
   by ``DOCGEN_PLAYWRIGHT_OUTPUT`` (set by ``docgen compose`` /
   ``PlaywrightRunner``).

Selectors used during the recording can be tuned per project via
``DOCGEN_PLAYWRIGHT_WAIT_SELECTOR`` (default: ``body``).

Requires: Node.js, ``npm ci`` already run in the detected project, the
``playwright`` Python package, and Chromium installed
(``python -m playwright install chromium``).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "playwright package required: pip install playwright && playwright install chromium"
    ) from exc


_PLAYWRIGHT_PKG_DEPS = ("@playwright/test", "playwright", "playwright-core")
_PLAYWRIGHT_CONFIG_NAMES = (
    "playwright.config.js",
    "playwright.config.ts",
    "playwright.config.mjs",
    "playwright.config.cjs",
)
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "__pycache__",
        "dist",
        "build",
        "target",
        "archive",
    }
)


def _repo_root() -> Path:
    # docs/demos/scripts/this.py -> parents: scripts, demos, docs, repo
    return Path(__file__).resolve().parent.parent.parent.parent


def _package_json_has_playwright(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(section)
        if isinstance(deps, dict) and any(name in deps for name in _PLAYWRIGHT_PKG_DEPS):
            return True
    return False


def _detect_playwright_project(repo_root: Path) -> Path | None:
    """Return the first detected Playwright project under ``repo_root`` (BFS by depth)."""
    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        d = Path(dirpath)
        try:
            depth = len(d.resolve().relative_to(repo_root.resolve()).parts)
        except ValueError:
            dirnames[:] = []
            continue
        if depth > 6:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(n for n in dirnames if n not in _SKIP_DIRS and not n.startswith("."))
        names = set(filenames)
        if names & set(_PLAYWRIGHT_CONFIG_NAMES):
            matches.append(d)
            continue
        if "package.json" in names and _package_json_has_playwright(d / "package.json"):
            matches.append(d)
    if not matches:
        return None
    matches.sort(key=lambda p: (len(p.relative_to(repo_root).parts), str(p)))
    return matches[0]


def _resolve_fixture(repo_root: Path) -> Path:
    env = os.environ.get("DOCGEN_PLAYWRIGHT_FIXTURE_DIR", "").strip()
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = repo_root / p
        return p
    detected = _detect_playwright_project(repo_root)
    if detected is None:
        raise SystemExit(
            "No Playwright project found under repo (looked for package.json with "
            "@playwright/test/playwright/playwright-core, or playwright.config.*). "
            "Set DOCGEN_PLAYWRIGHT_FIXTURE_DIR=path/to/project to override."
        )
    return detected


def _pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_http(url: str, timeout_sec: float = 40.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1.0)
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise RuntimeError(f"timeout waiting for {url}")


def main() -> None:
    out = Path(os.environ["DOCGEN_PLAYWRIGHT_OUTPUT"])
    out.parent.mkdir(parents=True, exist_ok=True)
    width = int(os.environ.get("DOCGEN_PLAYWRIGHT_WIDTH", "1280"))
    height = int(os.environ.get("DOCGEN_PLAYWRIGHT_HEIGHT", "720"))
    wait_selector = os.environ.get("DOCGEN_PLAYWRIGHT_WAIT_SELECTOR", "body").strip() or "body"

    fixture = _resolve_fixture(_repo_root())
    if not (fixture / "package.json").is_file():
        raise SystemExit(f"Playwright project missing package.json: {fixture}")

    env_url = os.environ.get("DOCGEN_PLAYWRIGHT_URL", "").strip()
    proc = None
    base_url = env_url.rstrip("/")

    if not base_url:
        port = _pick_port()
        base_url = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port), "--strictPort"],
            cwd=str(fixture),
            env={**os.environ, "BROWSER": "none"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_http(f"{base_url}/")
        except RuntimeError:
            err = proc.stderr.read() if proc.stderr else ""
            proc.terminate()
            raise SystemExit(f"dev server did not start ({base_url}): {err[:800]}") from None

    tmp_dir = out.parent / f".pw_record_{os.getpid()}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=str(tmp_dir),
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()
            page.goto(f"{base_url}/", wait_until="domcontentloaded")
            page.wait_for_selector(wait_selector, timeout=30_000)
            page.wait_for_timeout(400)
            page.close()
            context.close()
            browser.close()
    finally:
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    videos = sorted(tmp_dir.glob("*.webm"))
    if not videos:
        raise SystemExit(f"no WebM under {tmp_dir}")
    shutil.move(str(videos[0]), str(out))
    shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
