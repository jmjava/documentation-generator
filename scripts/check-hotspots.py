#!/usr/bin/env python3
"""Hotspot gate.

Fails when a changed Python file is both complex and in the top change-frequency
set. A change to a quiet file passes, including when that file is complex. A
change to a frequent file that is not complex passes.

Complex means any function with CCN > 10 or NLOC > 80 (same limits as
check-complexity.py). Frequency is the number of commits on --base that touch
the file, among Python files present at that revision. The top set is the
--top files by that count; ties at the cutoff are included.
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_CCN = 10
DEFAULT_NLOC = 80
DEFAULT_TOP = 10


def git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).rstrip("\n")


def changed_python_files(repo: Path, base: str, paths: list[str]) -> list[str]:
    rels = git(
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        f"{base}...HEAD",
        "--",
        *paths,
        cwd=repo,
    )
    files = []
    for line in rels.splitlines():
        line = line.strip()
        if line.endswith(".py"):
            files.append(line)
    return files


def python_files_at(repo: Path, rev: str, paths: list[str]) -> set[str]:
    listed = git("ls-tree", "-r", "--name-only", rev, "--", *paths, cwd=repo)
    return {line.strip() for line in listed.splitlines() if line.strip().endswith(".py")}


def commit_counts(repo: Path, rev: str, paths: list[str]) -> dict[str, int]:
    log = git("log", rev, "--pretty=format:", "--name-only", "--", *paths, cwd=repo)
    counts: dict[str, int] = {}
    for line in log.splitlines():
        line = line.strip()
        if not line.endswith(".py"):
            continue
        counts[line] = counts.get(line, 0) + 1
    return counts


def top_frequency(counts: dict[str, int], top_n: int) -> set[str]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if not ranked or top_n < 1:
        return set()
    cutoff = ranked[min(top_n, len(ranked)) - 1][1]
    return {path for path, count in ranked if count >= cutoff and count > 0}


def lizard_rows(source: str, filename: str) -> list[dict[str, str]]:
    if not source.strip():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / Path(filename).name
        dest.write_text(source, encoding="utf-8")
        csv_path = Path(tmp) / "out.csv"
        subprocess.run(
            ["lizard", "-l", "python", "-C", "999", "-L", "999999", "-o", str(csv_path), str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
        text = csv_path.read_text(encoding="utf-8")
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if len(rec) < 9:
            continue
        rows.append({"nloc": rec[0], "ccn": rec[1], "name": rec[7]})
    return rows


def function_peaks(repo: Path, rel: str) -> tuple[int, int] | None:
    try:
        source = git("show", f"HEAD:{rel}", cwd=repo)
    except subprocess.CalledProcessError:
        return None
    rows = lizard_rows(source, rel)
    if not rows:
        return (0, 0)
    max_ccn = max(int(row["ccn"]) for row in rows)
    max_nloc = max(int(row["nloc"]) for row in rows)
    return max_ccn, max_nloc


def hotspot_failures(
    repo: Path,
    changed: list[str],
    hot: set[str],
    counts: dict[str, int],
    ccn_limit: int,
    nloc_limit: int,
) -> list[str]:
    failures = []
    for rel in changed:
        if rel not in hot:
            continue
        peaks = function_peaks(repo, rel)
        if peaks is None:
            continue
        ccn, nloc = peaks
        if ccn > ccn_limit or nloc > nloc_limit:
            failures.append(
                f"HOTSPOT {rel} commits={counts.get(rel, 0)} "
                f"maxCCN={ccn} maxNLOC={nloc} (limits {ccn_limit}/{nloc_limit})"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ccn", type=int, default=DEFAULT_CCN)
    parser.add_argument("--nloc", type=int, default=DEFAULT_NLOC)
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--paths", nargs="*", default=["."])
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    try:
        changed = changed_python_files(repo, args.base, args.paths)
        present = python_files_at(repo, args.base, args.paths)
        counts = commit_counts(repo, args.base, args.paths)
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {exc}", file=sys.stderr)
        return 2
    if not changed:
        print("check-hotspots: no changed Python files")
        return 0
    ranked = {path: count for path, count in counts.items() if path in present}
    hot = top_frequency(ranked, args.top)
    try:
        failures = hotspot_failures(repo, changed, hot, counts, args.ccn, args.nloc)
    except subprocess.CalledProcessError as exc:
        print(f"lizard failed: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("check-hotspots: FAIL", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    print(f"check-hotspots: PASS ({len(changed)} file(s), {len(hot)} hotspot path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
