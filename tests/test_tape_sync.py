"""Tests for syncing VHS Sleep values from timing.json."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from docgen.config import Config
from docgen.tape_sync import TapeSynchronizer


def _write_cfg(tmp_path: Path, cfg: dict) -> Config:
    path = tmp_path / "docgen.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return Config.from_yaml(path)


def test_sync_rewrites_sleep_values(tmp_path: Path) -> None:
    cfg = {
        "dirs": {
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
            "narration": "narration",
        },
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "vhs", "tape": "01-demo.tape", "source": "01-demo.mp4"}},
        "vhs": {
            "sync_from_timing": True,
            "typing_ms_per_char": 100,
            "max_typing_sec": 0.5,
            "min_sleep_sec": 0.1,
        },
    }
    c = _write_cfg(tmp_path, cfg)
    (tmp_path / "animations").mkdir(parents=True, exist_ok=True)
    (tmp_path / "terminal").mkdir(parents=True, exist_ok=True)

    timing = {
        "01-demo": {
            "segments": [
                {"start": 0.0, "end": 2.0},
                {"start": 2.0, "end": 4.0},
            ]
        }
    }
    (tmp_path / "animations" / "timing.json").write_text(json.dumps(timing), encoding="utf-8")

    tape = tmp_path / "terminal" / "01-demo.tape"
    tape.write_text(
        "\n".join(
            [
                'Set Shell "bash"',
                "Show",
                'Type "echo one"',
                "Enter",
                "Sleep 5s",
                'Type "echo two"',
                "Enter",
                "Sleep 4s",
                "",
            ]
        ),
        encoding="utf-8",
    )

    results = TapeSynchronizer(c).sync()
    assert len(results) == 1
    assert results[0].changes
    new_text = tape.read_text(encoding="utf-8")
    assert "Sleep 5s" not in new_text
    assert "Sleep 4s" not in new_text
    assert "Sleep " in new_text


def test_sync_dry_run_does_not_write(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "terminal": "terminal"},
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {"01": {"type": "vhs", "tape": "01-demo.tape", "source": "01-demo.mp4"}},
    }
    c = _write_cfg(tmp_path, cfg)
    (tmp_path / "animations").mkdir(parents=True, exist_ok=True)
    (tmp_path / "terminal").mkdir(parents=True, exist_ok=True)
    (tmp_path / "animations" / "timing.json").write_text(
        json.dumps({"01-demo": {"segments": [{"start": 0.0, "end": 2.0}]}}),
        encoding="utf-8",
    )
    tape = tmp_path / "terminal" / "01-demo.tape"
    original = "\n".join(['Show', 'Type "echo one"', "Enter", "Sleep 5s", ""]) + "\n"
    tape.write_text(original, encoding="utf-8")

    results = TapeSynchronizer(c).sync(dry_run=True)
    assert len(results) == 1
    assert results[0].changes
    assert tape.read_text(encoding="utf-8") == original


def test_sync_segment_filter(tmp_path: Path) -> None:
    cfg = {
        "dirs": {"animations": "animations", "terminal": "terminal"},
        "segments": {"default": ["01", "02"], "all": ["01", "02"]},
        "segment_names": {"01": "01-demo", "02": "02-demo"},
        "visual_map": {
            "01": {"type": "vhs", "tape": "01-demo.tape", "source": "01-demo.mp4"},
            "02": {"type": "vhs", "tape": "02-demo.tape", "source": "02-demo.mp4"},
        },
    }
    c = _write_cfg(tmp_path, cfg)
    (tmp_path / "animations").mkdir(parents=True, exist_ok=True)
    (tmp_path / "terminal").mkdir(parents=True, exist_ok=True)
    (tmp_path / "animations" / "timing.json").write_text(
        json.dumps(
            {
                "01-demo": {"segments": [{"start": 0.0, "end": 2.0}]},
                "02-demo": {"segments": [{"start": 0.0, "end": 2.0}]},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "terminal" / "01-demo.tape").write_text(
        "\n".join(["Show", 'Type "a"', "Enter", "Sleep 4s", ""]) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "terminal" / "02-demo.tape").write_text(
        "\n".join(["Show", 'Type "b"', "Enter", "Sleep 4s", ""]) + "\n",
        encoding="utf-8",
    )

    results = TapeSynchronizer(c).sync(segment="01")
    assert len(results) == 1
    assert results[0].tape == "01-demo.tape"

