"""Tests for pipeline retry behavior around compose FREEZE GUARD."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docgen.compose import ComposeError
from docgen.pipeline import Pipeline


def _patch_pipeline_stages(monkeypatch, composer_cls, calls: list[str]) -> None:
    class FakeTimestampExtractor:
        def __init__(self, _config) -> None:
            pass

        def extract_all(self) -> None:
            calls.append("timestamps")

    class FakeManimRunner:
        def __init__(self, _config) -> None:
            pass

        def render(self, scene=None) -> None:
            calls.append("manim")

    class FakeValidator:
        def __init__(self, _config) -> None:
            pass

        def run_all(self):
            calls.append("validate")
            return []

        def print_report(self, _reports) -> None:
            calls.append("print-report")

    class FakeConcatBuilder:
        def __init__(self, _config) -> None:
            pass

        def build(self) -> None:
            calls.append("concat")

    class FakePagesGenerator:
        def __init__(self, _config) -> None:
            pass

        def generate_all(self, force=False) -> None:
            calls.append(f"pages:{force}")

    import docgen.concat as concat_module
    import docgen.manim_runner as manim_module
    import docgen.pages as pages_module
    import docgen.timestamps as timestamps_module
    import docgen.validate as validate_module
    import docgen.compose as compose_module

    monkeypatch.setattr(timestamps_module, "TimestampExtractor", FakeTimestampExtractor)
    monkeypatch.setattr(manim_module, "ManimRunner", FakeManimRunner)
    monkeypatch.setattr(validate_module, "Validator", FakeValidator)
    monkeypatch.setattr(concat_module, "ConcatBuilder", FakeConcatBuilder)
    monkeypatch.setattr(pages_module, "PagesGenerator", FakePagesGenerator)
    monkeypatch.setattr(compose_module, "Composer", composer_cls)


def test_retry_manim_after_freeze_guard(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class FlakyComposer:
        attempts = 0

        def __init__(self, _config) -> None:
            pass

        def compose_segments(self, _segments) -> int:
            FlakyComposer.attempts += 1
            calls.append(f"compose:{FlakyComposer.attempts}")
            if FlakyComposer.attempts == 1:
                raise ComposeError("FREEZE GUARD: short visual")
            return 1

    _patch_pipeline_stages(monkeypatch, FlakyComposer, calls)

    animations_dir = tmp_path / "animations"
    media_dir = animations_dir / "media"
    media_dir.mkdir(parents=True)
    (media_dir / "cache.bin").write_text("cache", encoding="utf-8")

    cfg = SimpleNamespace(
        animations_dir=animations_dir,
        segments_all=["01"],
        sync_vhs_after_timestamps=False,
        visual_map={},
    )

    Pipeline(cfg).run(skip_tts=True, skip_vhs=True, retry_manim_on_freeze=True)

    assert FlakyComposer.attempts == 2
    assert calls.count("manim") == 2, "Manim should run once initially and once on retry"
    assert not media_dir.exists(), "Retry path should clear Manim cache directory"


def test_no_retry_when_flag_disabled(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class AlwaysFailComposer:
        def __init__(self, _config) -> None:
            pass

        def compose_segments(self, _segments) -> int:
            calls.append("compose")
            raise ComposeError("FREEZE GUARD: short visual")

    _patch_pipeline_stages(monkeypatch, AlwaysFailComposer, calls)

    animations_dir = tmp_path / "animations"
    media_dir = animations_dir / "media"
    media_dir.mkdir(parents=True)

    cfg = SimpleNamespace(
        animations_dir=animations_dir,
        segments_all=["01"],
        sync_vhs_after_timestamps=False,
        visual_map={},
    )

    with pytest.raises(ComposeError, match="FREEZE GUARD"):
        Pipeline(cfg).run(skip_tts=True, skip_vhs=True, retry_manim_on_freeze=False)

    assert calls.count("manim") == 1
    assert media_dir.exists(), "Without retry flag, Manim cache should be untouched"
