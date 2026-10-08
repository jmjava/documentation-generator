#!/usr/bin/env python3
"""Compare a mutmut export to the committed survived ceiling.

Reads mutants/mutmut-cicd-stats.json and config/mutation-path-filters-baseline.json.
Fails when survived mutants increase. Does not write the baseline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "config" / "mutation-path-filters-baseline.json"
DEFAULT_STATS = ROOT / "mutants" / "mutmut-cicd-stats.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    args = parser.parse_args()
    if not args.baseline.is_file():
        print(f"missing mutation baseline: {args.baseline}", file=sys.stderr)
        return 2
    if not args.stats.is_file():
        print(f"missing mutmut stats: {args.stats}", file=sys.stderr)
        return 2
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    if int(stats.get("check_was_interrupted_by_user") or 0) > 0:
        print("check-mutation-score: FAIL interrupted run", file=sys.stderr)
        return 1
    if int(stats.get("total") or 0) <= 0:
        print("check-mutation-score: FAIL empty mutmut export", file=sys.stderr)
        return 1
    allowed = int(baseline["survived"])
    survived = int(stats["survived"])
    if survived > allowed:
        print(
            f"check-mutation-score: FAIL survived {allowed} -> {survived}",
            file=sys.stderr,
        )
        return 1
    print(f"check-mutation-score: PASS survived {survived} (ceiling {allowed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
