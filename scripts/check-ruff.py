#!/usr/bin/env python3
"""Fail when ruff reports a new finding.

The committed baseline counts today's findings under the repo ruff config.
A higher count, or a finding that is not listed, fails. Removed findings are
allowed. This script never writes the baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def finding_key(item: dict, root: Path) -> str:
    filename = str(item.get("filename", ""))
    path = Path(filename)
    if path.is_absolute():
        try:
            filename = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            filename = path.as_posix()
    code = str(item.get("code", ""))
    message = str(item.get("message", ""))
    return f"{filename} {code} {message}"


def parse_baseline(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        count_text, key = line.split(" ", 1)
        counts[key] = int(count_text)
    return counts


def current_counts(paths: list[str], cwd: Path) -> Counter[str]:
    proc = subprocess.run(
        ["ruff", "check", *paths, "--output-format", "json", "--no-cache"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"ruff exited {proc.returncode}")
    payload = proc.stdout.strip() or "[]"
    data = json.loads(payload)
    if not isinstance(data, list):
        raise RuntimeError("ruff JSON was not a list")
    counts: Counter[str] = Counter()
    for item in data:
        if isinstance(item, dict):
            counts[finding_key(item, cwd)] += 1
    return counts


def new_findings(current: Counter[str], baseline: dict[str, int]) -> list[str]:
    failures = []
    for key, count in sorted(current.items()):
        allowed = baseline.get(key, 0)
        if count > allowed:
            failures.append(f"NEW {key} count {allowed} -> {count}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "config" / "ruff-baseline.txt")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    paths = args.paths or ["src", "tests"]
    if not args.baseline.is_file():
        print(f"missing ruff baseline: {args.baseline}", file=sys.stderr)
        return 2
    baseline = parse_baseline(args.baseline.read_text(encoding="utf-8"))
    try:
        current = current_counts(paths, ROOT)
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    failures = new_findings(current, baseline)
    if failures:
        print("check-ruff: FAIL", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    print(f"check-ruff: PASS ({len(current)} finding key(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
