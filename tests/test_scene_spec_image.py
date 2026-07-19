"""Scene-spec **image elements**: schema validation, compilation, timing behavior."""

from __future__ import annotations

import copy

import pytest

from docgen.scene_spec import (
    SceneSpecError,
    compile_scene_class,
    iter_image_elements,
    sync_row_labels_to_whisper_words,
    validate_scene_spec,
)


def _image_spec() -> dict:
    return {
        "segment_id": "1",
        "class_name": "ImgScene",
        "timing_key": "01-x",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [
            {
                "run_time": 0.5,
                "boxes": [
                    {
                        "label": "Alpha",
                        "color": "C_GREEN",
                        "width": 3.0,
                        "height": 1.0,
                        "font_size": 20,
                    },
                    {
                        "image": "images/arch.png",
                        "width": 4.0,
                        "height": 2.5,
                        "prompt": "clean diagram of the architecture",
                    },
                ],
            },
        ],
    }


class TestImageElementValidation:
    def test_valid_image_element_passes(self) -> None:
        validate_scene_spec(_image_spec())

    def test_rejects_absolute_image_path(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["image"] = "/etc/passwd.png"
        with pytest.raises(SceneSpecError, match="relative"):
            validate_scene_spec(spec)

    def test_rejects_parent_traversal(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["image"] = "../outside.png"
        with pytest.raises(SceneSpecError, match="relative"):
            validate_scene_spec(spec)

    def test_rejects_color_on_image_element(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["color"] = "C_GREEN"
        with pytest.raises(SceneSpecError, match="not allowed on an image"):
            validate_scene_spec(spec)

    def test_rejects_font_size_on_image_element(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["font_size"] = 18
        with pytest.raises(SceneSpecError, match="not allowed on an image"):
            validate_scene_spec(spec)

    def test_requires_width_and_height(self) -> None:
        spec = _image_spec()
        del spec["rows"][0]["boxes"][1]["height"]
        with pytest.raises(SceneSpecError, match="missing height"):
            validate_scene_spec(spec)

    def test_rejects_empty_prompt(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["prompt"] = "   "
        with pytest.raises(SceneSpecError, match="prompt"):
            validate_scene_spec(spec)


class TestImageElementCompile:
    def test_compile_emits_image_helper_and_group(self) -> None:
        out = compile_scene_class(_image_spec())
        assert "_bx_0_0_1 = _image('images/arch.png', 4.0, 2.5)" in out
        # ImageMobject is not a VMobject: rows/stack on an image page use Group.
        assert "_row_0_0 = Group(_bx_0_0_0, _bx_0_0_1).arrange(RIGHT" in out
        assert "_p0_stack = Group(_row_0_0)" in out
        assert "VGroup(" not in out
        assert "self.timed_play(FadeIn(_bx_0_0_1), run_time=0.5)" in out

    def test_pure_box_spec_still_uses_vgroup(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"] = [spec["rows"][0]["boxes"][0]]
        out = compile_scene_class(spec)
        assert "VGroup(" in out
        assert "Group(" not in out.replace("VGroup(", "")


class TestImageElementTiming:
    WORDS = [
        {"start": 0.5, "end": 0.9, "word": " Alpha"},
        {"start": 1.4, "end": 1.9, "word": " architecture"},
        {"start": 2.2, "end": 2.6, "word": " done"},
    ]

    def test_unlabeled_image_keeps_authored_wait_word(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["wait_word"] = 2
        out = sync_row_labels_to_whisper_words(
            copy.deepcopy(spec), self.WORDS, overwrite=True
        )
        boxes = out["rows"][0]["boxes"]
        assert boxes[0]["wait_word"] == 0  # Alpha matched from transcript
        assert boxes[1]["wait_word"] == 2  # image element untouched

    def test_labeled_image_matches_transcript(self) -> None:
        spec = _image_spec()
        spec["rows"][0]["boxes"][1]["label"] = "architecture"
        out = sync_row_labels_to_whisper_words(
            copy.deepcopy(spec), self.WORDS, overwrite=True
        )
        boxes = out["rows"][0]["boxes"]
        assert boxes[1]["wait_word"] == 1


def test_iter_image_elements_collects_across_pages() -> None:
    spec = _image_spec()
    els = iter_image_elements(spec)
    assert len(els) == 1
    assert els[0]["image"] == "images/arch.png"
    assert "prompt" in els[0]


class TestEnsureImageHelper:
    def test_bootstrap_header_defines_image_helper(self) -> None:
        from docgen.manim_scene_support import BOOTSTRAP_HEADER

        assert "def _image(" in BOOTSTRAP_HEADER
        assert "ImageMobject" in BOOTSTRAP_HEADER

    def test_appends_helper_to_legacy_scenes_py(self, tmp_path) -> None:
        from docgen.manim_scene_support import BOOTSTRAP_HEADER, ensure_image_helper

        legacy = "\n".join(
            line for line in BOOTSTRAP_HEADER.splitlines() if True
        )
        # Simulate a pre-image bundle: strip the _image helper block.
        start = legacy.index("def _image(")
        end = legacy.index("class _TimedScene")
        legacy = legacy[:start] + legacy[end:]
        scenes = tmp_path / "scenes.py"
        scenes.write_text(legacy, encoding="utf-8")

        assert ensure_image_helper(scenes) is True
        text = scenes.read_text(encoding="utf-8")
        assert "def _image(" in text
        # Idempotent on second run.
        assert ensure_image_helper(scenes) is False

    def test_noop_when_helper_present(self, tmp_path) -> None:
        from docgen.manim_scene_support import BOOTSTRAP_HEADER, ensure_image_helper

        scenes = tmp_path / "scenes.py"
        scenes.write_text(BOOTSTRAP_HEADER, encoding="utf-8")
        assert ensure_image_helper(scenes) is False
