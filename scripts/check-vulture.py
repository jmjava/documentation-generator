#!/usr/bin/env python3
"""Fail when vulture reports a new high-confidence finding.

The committed baseline counts today's findings. A higher count, or a finding
that is not listed, fails. Removed findings are allowed. This script never
writes the baseline.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_CONFIDENCE = "80"
_LINE = re.compile(r"^(.*?):\d+: (.*?)(?: \(\d+% confidence\))?$")


def finding_key(line: str) -> str | None:
    match = _LINE.match(line.strip())
    if match is None:
        return None
    return f"{match.group(1)} {match.group(2)}"


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
        [sys.executable, "-m", "vulture", *paths, "--min-confidence", MIN_CONFIDENCE],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 3):
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"vulture exited {proc.returncode}")
    counts: Counter[str] = Counter()
    for line in proc.stdout.splitlines():
        key = finding_key(line)
        if key is not None:
            counts[key] += 1
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
    parser.add_argument("--baseline", type=Path, default=ROOT / "config" / "vulture-baseline.txt")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    paths = args.paths or ["src", "tests"]
    if not args.baseline.is_file():
        print(f"missing vulture baseline: {args.baseline}", file=sys.stderr)
        return 2
    baseline = parse_baseline(args.baseline.read_text(encoding="utf-8"))
    try:
        current = current_counts(paths, ROOT)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2
    failures = new_findings(current, baseline)
    if failures:
        print("check-vulture: FAIL", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    print(f"check-vulture: PASS ({len(current)} finding key(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
