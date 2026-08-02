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

        def render(self, scenes=None, *, scene=None) -> None:
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
    import docgen.compose as compose_module
    import docgen.image_generate as image_module
    import docgen.manim_runner as manim_module
    import docgen.pages as pages_module
    import docgen.timestamps as timestamps_module
    import docgen.validate as validate_module

    monkeypatch.setattr(timestamps_module, "TimestampExtractor", FakeTimestampExtractor)
    monkeypatch.setattr(manim_module, "ManimRunner", FakeManimRunner)
    monkeypatch.setattr(validate_module, "Validator", FakeValidator)
    monkeypatch.setattr(concat_module, "ConcatBuilder", FakeConcatBuilder)
    monkeypatch.setattr(pages_module, "PagesGenerator", FakePagesGenerator)
    monkeypatch.setattr(compose_module, "Composer", composer_cls)
    monkeypatch.setattr(
        image_module,
        "generate_missing_images_for_bundle",
        lambda _cfg: calls.append("images") or [],
    )


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
        visual_map={"01": {"type": "manim", "scene": "Scene01"}},
        pipeline_manim_scene_names=lambda: ["Scene01"],
    )

    Pipeline(cfg).run(
        skip_tts=True, retry_manim_on_freeze=True, skip_scene_retime=True
    )

    assert FlakyComposer.attempts == 2
    assert calls.count("manim") == 2, "Manim should run once initially and once on retry"
    assert not media_dir.exists(), "Retry path should clear Manim cache directory"


def test_pipeline_retimes_existing_specs_after_timestamps(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class OkComposer:
        def __init__(self, _config) -> None:
            pass

        def compose_segments(self, _segments) -> int:
            calls.append("compose")
            return 1

    _patch_pipeline_stages(monkeypatch, OkComposer, calls)

    import docgen.scene_retime as retime_module

    def fake_retime_all(cfg, **_kwargs):
        calls.append("retime")
        return (
            [
                {
                    "path": cfg.animations_dir / "specs" / "01.scene.yaml",
                    "class_name": "Scene01",
                    "timing_key": "01",
                    "wrote": True,
                }
            ],
            [],
        )

    monkeypatch.setattr(retime_module, "retime_compile_all", fake_retime_all)
    monkeypatch.setattr(
        retime_module,
        "list_scene_spec_paths",
        lambda cfg, segment_id=None: [cfg.animations_dir / "specs" / "01.scene.yaml"],
    )

    animations_dir = tmp_path / "animations"
    (animations_dir / "specs").mkdir(parents=True)

    cfg = SimpleNamespace(
        animations_dir=animations_dir,
        segments_all=["01"],
        visual_map={"01": {"type": "manim", "scene": "Scene01"}},
        pipeline_manim_scene_names=lambda: ["Scene01"],
    )

    Pipeline(cfg).run(skip_tts=True)

    assert calls.index("timestamps") < calls.index("retime")
    assert calls.index("retime") < calls.index("manim")
    assert "compose" in calls


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
        visual_map={"01": {"type": "manim", "scene": "Scene01"}},
        pipeline_manim_scene_names=lambda: ["Scene01"],
    )

    with pytest.raises(ComposeError, match="FREEZE GUARD"):
        Pipeline(cfg).run(
            skip_tts=True, retry_manim_on_freeze=False, skip_scene_retime=True
        )

    assert calls.count("manim") == 1
    assert media_dir.exists(), "Without retry flag, Manim cache should be untouched"


def test_pipeline_auto_regens_scene_specs_when_missing(tmp_path, monkeypatch) -> None:
    """First run with manim segments and no specs → scene-spec-generate."""
    calls: list[str] = []

    class OkComposer:
        def __init__(self, _config) -> None:
            pass

        def compose_segments(self, _segments) -> int:
            calls.append("compose")
            return 1

    _patch_pipeline_stages(monkeypatch, OkComposer, calls)

    import docgen.scene_retime as retime_module
    import docgen.scene_spec_generate as ssg

    monkeypatch.setattr(
        retime_module, "list_scene_spec_paths", lambda cfg, segment_id=None: []
    )

    def fake_generate(cfg, sid, **_kwargs):
        calls.append(f"scene-spec:{sid}")
        specs = cfg.animations_dir / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        path = specs / f"{sid}.scene.yaml"
        path.write_text("segment_id: '01'\nclass_name: Scene01\nrows: []\n", encoding="utf-8")
        return SimpleNamespace(
            seg_name=sid,
            yaml_text=path.read_text(encoding="utf-8"),
            spec={"segment_id": sid, "class_name": "Scene01", "rows": []},
        )

    monkeypatch.setattr(ssg, "generate_scene_spec", fake_generate)
    monkeypatch.setattr(
        ssg,
        "linted_class_block_from_spec",
        lambda cfg, spec, timing_key=None: ("class Scene01: pass", spec),
    )
    monkeypatch.setattr(
        ssg, "inject_class_block_into_scenes_py", lambda *a, **k: calls.append("inject")
    )

    animations_dir = tmp_path / "animations"
    animations_dir.mkdir(parents=True)

    cfg = SimpleNamespace(
        animations_dir=animations_dir,
        segments_all=["01"],
        visual_map={"01": {"type": "manim", "class": "Scene01"}},
        pipeline_manim_scene_names=lambda: ["Scene01"],
    )

    Pipeline(cfg).run(skip_tts=True)

    assert "scene-spec:01" in calls
    assert "inject" in calls
    assert calls.index("timestamps") < calls.index("scene-spec:01")
    assert calls.index("scene-spec:01") < calls.index("manim")
