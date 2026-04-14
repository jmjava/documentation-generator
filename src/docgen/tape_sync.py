"""Sync VHS Sleep values from animations/timing.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docgen.config import Config


@dataclass
class TapeSyncChange:
    line_no: int
    old_sleep_sec: float
    new_sleep_sec: float
    old_line: str
    new_line: str


@dataclass
class TapeSyncResult:
    tape: str
    timing_key: str | None = None
    duration_sec: float = 0.0
    blocks_found: int = 0
    changes: list[TapeSyncChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    wrote_file: bool = False


@dataclass
class _TapeBlock:
    type_idx: int
    enter_idx: int
    sleep_idx: int
    typed_text: str


class TapeSynchronizer:
    def __init__(self, config: Config) -> None:
        self.config = config

    def sync(self, segment: str | None = None, dry_run: bool = False) -> list[TapeSyncResult]:
        timing = self._load_timing_json()
        if not timing:
            print("[sync-vhs] No timing.json data found. Run `docgen timestamps` first.")
            return []

        targets = self._collect_targets(segment=segment)
        if not targets:
            if segment:
                print(f"[sync-vhs] No VHS targets matched segment filter '{segment}'.")
            else:
                print("[sync-vhs] No VHS tapes found to sync.")
            return []

        results: list[TapeSyncResult] = []
        for tape_path, timing_keys in targets:
            result = self._sync_one(
                tape_path=tape_path,
                timing=timing,
                timing_keys=timing_keys,
                dry_run=dry_run,
            )
            self._print_result(result, dry_run=dry_run)
            results.append(result)

        changed = sum(1 for r in results if r.changes)
        wrote = sum(1 for r in results if r.wrote_file)
        print(
            f"[sync-vhs] Done: {len(results)} tape(s), {changed} with changes, "
            f"{wrote} file(s) written."
        )
        return results

    def _collect_targets(self, segment: str | None) -> list[tuple[Path, list[str]]]:
        query = segment.lower().strip() if segment else None
        targets: list[tuple[Path, list[str]]] = []

        for seg_id in sorted(self.config.visual_map):
            vmap = self.config.visual_map.get(seg_id, {})
            if str(vmap.get("type", "")).lower() != "vhs":
                continue
            seg_name = self.config.resolve_segment_name(seg_id)
            tape_name = str(vmap.get("tape", "")).strip()
            if not tape_name:
                source_name = str(vmap.get("source", "")).strip()
                if source_name:
                    tape_name = f"{Path(source_name).stem}.tape"
            if not tape_name:
                continue

            tape_path = self.config.terminal_dir / tape_name
            tape_stem = tape_path.stem
            if query and query not in {seg_id.lower(), seg_name.lower(), tape_stem.lower()}:
                continue

            timing_keys = [seg_name, seg_id, tape_stem]
            targets.append((tape_path, self._unique_strings(timing_keys)))

        if targets:
            return targets

        # Fallback for legacy projects without visual_map tape metadata.
        for tape_path in sorted(self.config.terminal_dir.glob("*.tape")):
            tape_stem = tape_path.stem
            if query and query != tape_stem.lower():
                continue
            targets.append((tape_path, [tape_stem]))
        return targets

    @staticmethod
    def _unique_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                out.append(value)
        return out

    def _load_timing_json(self) -> dict[str, Any]:
        path = self.config.animations_dir / "timing.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            print(f"[sync-vhs] Invalid JSON: {path}")
            return {}

    def _sync_one(
        self,
        tape_path: Path,
        timing: dict[str, Any],
        timing_keys: list[str],
        dry_run: bool,
    ) -> TapeSyncResult:
        result = TapeSyncResult(tape=tape_path.name)
        if not tape_path.exists():
            result.warnings.append(f"missing tape: {tape_path}")
            return result

        timing_key = next((k for k in timing_keys if k in timing), None)
        if not timing_key:
            result.warnings.append(f"no timing key found (tried: {', '.join(timing_keys)})")
            return result
        result.timing_key = timing_key

        duration_sec = self._timing_duration_sec(timing[timing_key])
        result.duration_sec = duration_sec
        if duration_sec <= 0:
            result.warnings.append(f"timing data for '{timing_key}' has zero duration")
            return result

        lines = tape_path.read_text(encoding="utf-8").splitlines()
        blocks = self._find_blocks(lines)
        result.blocks_found = len(blocks)
        if not blocks:
            result.warnings.append("no Type/Enter/Sleep blocks found after first Show")
            return result

        window_sec = duration_sec / len(blocks)
        ms_per_char = max(1, self.config.typing_ms_per_char)
        max_typing_sec = max(0.0, self.config.max_typing_sec)
        min_sleep_sec = max(0.0, self.config.min_sleep_sec)

        for block in blocks:
            old_line = lines[block.sleep_idx]
            old_sleep = self._parse_sleep_sec(old_line)
            if old_sleep is None:
                continue

            typing_est = min(max_typing_sec, (len(block.typed_text) * ms_per_char) / 1000.0)
            new_sleep = max(min_sleep_sec, window_sec - typing_est)
            new_line = self._format_sleep_line(new_sleep)
            if new_line == old_line.strip():
                continue

            lines[block.sleep_idx] = new_line
            result.changes.append(
                TapeSyncChange(
                    line_no=block.sleep_idx + 1,
                    old_sleep_sec=old_sleep,
                    new_sleep_sec=new_sleep,
                    old_line=old_line,
                    new_line=new_line,
                )
            )

        if result.changes and not dry_run:
            tape_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result.wrote_file = True
        return result

    @staticmethod
    def _timing_duration_sec(entry: Any) -> float:
        if not isinstance(entry, dict):
            return 0.0

        max_end = 0.0
        for key in ("words", "segments"):
            values = entry.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                try:
                    max_end = max(max_end, float(item.get("end", 0)))
                except (TypeError, ValueError):
                    continue
        return max_end

    @staticmethod
    def _find_blocks(lines: list[str]) -> list[_TapeBlock]:
        show_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("Show"):
                show_idx = i
                break

        blocks: list[_TapeBlock] = []
        i = show_idx + 1
        while i < len(lines):
            current = lines[i].strip()
            if not current.startswith("Type "):
                i += 1
                continue

            type_idx = i
            typed_text = TapeSynchronizer._extract_typed_text(current)
            enter_idx: int | None = None
            sleep_idx: int | None = None

            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt.startswith("Type "):
                    break
                if enter_idx is None and nxt.startswith("Enter"):
                    enter_idx = j
                elif enter_idx is not None and nxt.startswith("Sleep "):
                    sleep_idx = j
                    break
                j += 1

            if enter_idx is not None and sleep_idx is not None:
                blocks.append(
                    _TapeBlock(
                        type_idx=type_idx,
                        enter_idx=enter_idx,
                        sleep_idx=sleep_idx,
                        typed_text=typed_text,
                    )
                )
            i = max(j, i + 1)

        return blocks

    @staticmethod
    def _extract_typed_text(type_line: str) -> str:
        payload = type_line[len("Type "):].strip()
        return TapeSynchronizer._unquote(payload)

    @staticmethod
    def _unquote(value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value

    @staticmethod
    def _parse_sleep_sec(line: str) -> float | None:
        match = re.match(r"^\s*Sleep\s+([0-9]*\.?[0-9]+)\s*(ms|s)?\s*$", line)
        if not match:
            return None
        value = float(match.group(1))
        unit = (match.group(2) or "s").lower()
        if unit == "ms":
            return value / 1000.0
        return value

    @staticmethod
    def _format_sleep_line(seconds: float) -> str:
        if seconds < 1.0:
            ms = max(1, int(round(seconds * 1000)))
            return f"Sleep {ms}ms"

        rounded = round(seconds, 2)
        if abs(rounded - round(rounded)) < 1e-9:
            return f"Sleep {int(round(rounded))}s"
        return f"Sleep {rounded:.2f}s"

    @staticmethod
    def _print_result(result: TapeSyncResult, dry_run: bool) -> None:
        prefix = "[sync-vhs] DRY-RUN" if dry_run else "[sync-vhs]"
        key_msg = result.timing_key or "no timing key"
        print(
            f"{prefix} {result.tape}: key={key_msg}, duration={result.duration_sec:.2f}s, "
            f"blocks={result.blocks_found}, changes={len(result.changes)}"
        )
        for warning in result.warnings:
            print(f"{prefix}   WARN: {warning}")
        for change in result.changes[:10]:
            print(
                f"{prefix}   L{change.line_no}: {change.old_line.strip()} -> "
                f"{change.new_line}"
            )


def sync_single_tape_from_timing(
    tape_path: str | Path,
    timing_entry: dict[str, Any],
    *,
    typing_ms_per_char: int = 45,
    max_typing_sec: float = 3.0,
    min_sleep_sec: float = 0.15,
    dry_run: bool = False,
) -> TapeSyncResult:
    """Pure helper used by tests and external callers."""
    path = Path(tape_path)
    fake_cfg = type(
        "_Cfg",
        (),
        {
            "typing_ms_per_char": typing_ms_per_char,
            "max_typing_sec": max_typing_sec,
            "min_sleep_sec": min_sleep_sec,
        },
    )()
    syncer = TapeSynchronizer(fake_cfg)  # type: ignore[arg-type]
    return syncer._sync_one(  # noqa: SLF001 - intentional internal reuse
        tape_path=path,
        timing={path.stem: timing_entry},
        timing_keys=[path.stem],
        dry_run=dry_run,
    )
