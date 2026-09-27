"""Tests for docgen.image_generate — spec-driven OpenAI image assets (fake image fn)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.image_align import ImageReviewResult
from docgen.image_generate import (
    DEFAULT_IMAGE_STYLE,
    ImageGenerationError,
    build_aligned_image_prompt,
    generate_images_for_spec,
    generate_missing_images_for_bundle,
    spec_files_for_bundle,
)

_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


def _write_spec(path: Path, *, image: str = "images/arch.png", prompt: str | None = "a diagram") -> Path:
    box: dict = {"image": image, "width": 4.0, "height": 2.5}
    if prompt is not None:
        box["prompt"] = prompt
    spec = {
        "segment_id": "1",
        "class_name": "ImgScene",
        "title": {"text": "T", "font_size": 40, "color": "C_WHITE"},
        "rows": [{"run_time": 0.5, "boxes": [box]}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(spec), encoding="utf-8")
    return path


@pytest.fixture
def cfg(tmp_path) -> Config:
    (tmp_path / "docgen.yaml").write_text(yaml.dump({"segments": {"all": ["1"]}}), encoding="utf-8")
    return Config.from_yaml(tmp_path / "docgen.yaml")


def test_generates_missing_asset(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml")
    results = generate_images_for_spec(cfg, spec, image_fn=lambda p: _PNG_BYTES)
    assert [r.status for r in results] == ["generated"]
    out = cfg.base_dir / "images" / "arch.png"
    assert out.read_bytes() == _PNG_BYTES


def test_existing_asset_skipped_unless_force(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml")
    out = cfg.base_dir / "images" / "arch.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"old")

    results = generate_images_for_spec(cfg, spec, image_fn=lambda p: _PNG_BYTES)
    assert [r.status for r in results] == ["exists"]
    assert out.read_bytes() == b"old"

    results = generate_images_for_spec(cfg, spec, force=True, image_fn=lambda p: _PNG_BYTES)
    assert [r.status for r in results] == ["generated"]
    assert out.read_bytes() == _PNG_BYTES


def test_missing_prompt_and_asset_fails_loud(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml", prompt=None)
    with pytest.raises(ImageGenerationError, match="no `prompt`"):
        generate_images_for_spec(cfg, spec, image_fn=lambda p: _PNG_BYTES)


def test_missing_prompt_with_existing_asset_is_ok(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml", prompt=None)
    out = cfg.base_dir / "images" / "arch.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"committed asset")
    results = generate_images_for_spec(cfg, spec, image_fn=lambda p: _PNG_BYTES)
    assert [r.status for r in results] == ["exists"]


def test_dry_run_reports_without_writing(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml")
    results = generate_images_for_spec(cfg, spec, dry_run=True, image_fn=lambda p: _PNG_BYTES)
    assert [r.status for r in results] == ["dry-run"]
    assert results[0].prompt == "a diagram"
    assert DEFAULT_IMAGE_STYLE.split(".")[0] in results[0].effective_prompt
    assert "Illustration request:" in results[0].effective_prompt
    assert not (cfg.base_dir / "images" / "arch.png").exists()


def test_bundle_scan_generates_only_missing(cfg: Config) -> None:
    _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml")
    _write_spec(
        cfg.animations_dir / "specs" / "02-y.scene.yaml",
        image="images/other.png",
        prompt="another diagram",
    )
    existing = cfg.base_dir / "images" / "other.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"committed")

    assert len(spec_files_for_bundle(cfg)) == 2
    msgs = generate_missing_images_for_bundle(cfg, image_fn=lambda p: _PNG_BYTES)
    assert msgs == ["01-x.scene.yaml: generated images/arch.png"]
    assert (cfg.base_dir / "images" / "arch.png").read_bytes() == _PNG_BYTES
    assert existing.read_bytes() == b"committed"


def test_empty_provider_bytes_fails_without_writing(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml")
    with pytest.raises(ImageGenerationError, match="empty bytes"):
        generate_images_for_spec(cfg, spec, image_fn=lambda p: b"")
    assert not (cfg.base_dir / "images" / "arch.png").exists()


def test_empty_provider_bytes_does_not_clobber_existing(cfg: Config) -> None:
    spec = _write_spec(cfg.animations_dir / "specs" / "01-x.scene.yaml")
    out = cfg.base_dir / "images" / "arch.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"committed")
    with pytest.raises(ImageGenerationError, match="empty bytes"):
        generate_images_for_spec(cfg, spec, force=True, image_fn=lambda p: b"")
    assert out.read_bytes() == b"committed"


def test_no_specs_dir_is_noop(cfg: Config) -> None:
    assert spec_files_for_bundle(cfg) == []
    assert generate_missing_images_for_bundle(cfg, image_fn=lambda p: _PNG_BYTES) == []


def test_aligned_prompt_is_what_the_provider_sees(cfg: Config) -> None:
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="clean diagram of the bootstrap pipeline",
    )
    (cfg.narration_dir).mkdir(parents=True, exist_ok=True)
    (cfg.narration_dir / "1.md").write_text(
        "The bootstrap pipeline seeds the cluster.\n", encoding="utf-8"
    )
    seen: list[str] = []

    def _capture(prompt: str) -> bytes:
        seen.append(prompt)
        return _PNG_BYTES

    generate_images_for_spec(cfg, spec, image_fn=_capture)
    assert seen
    assert "bootstrap pipeline" in seen[0]
    assert "Documented subject" in seen[0]
    assert seen[0] != "clean diagram of the bootstrap pipeline"


def test_unaligned_prompt_fails_before_provider(cfg: Config) -> None:
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="isometric render of the WidgetX orchestrator",
    )
    cfg.narration_dir.mkdir(parents=True, exist_ok=True)
    (cfg.narration_dir / "1.md").write_text(
        "The bootstrap pipeline seeds the cluster.\n", encoding="utf-8"
    )
    with pytest.raises(ImageGenerationError, match="image prompt alignment"):
        generate_images_for_spec(cfg, spec, image_fn=lambda p: _PNG_BYTES)
    assert not (cfg.base_dir / "images" / "arch.png").exists()


def test_align_with_docs_false_sends_authored_prompt(tmp_path: Path) -> None:
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump(
            {
                "segments": {"all": ["1"]},
                "image_generation": {"align_with_docs": False},
            }
        ),
        encoding="utf-8",
    )
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="isometric render of the WidgetX orchestrator",
    )
    cfg.narration_dir.mkdir(parents=True, exist_ok=True)
    (cfg.narration_dir / "1.md").write_text(
        "The bootstrap pipeline seeds the cluster.\n", encoding="utf-8"
    )
    seen: list[str] = []
    generate_images_for_spec(cfg, spec, image_fn=lambda p: seen.append(p) or _PNG_BYTES)
    assert seen == ["isometric render of the WidgetX orchestrator"]


def test_source_docs_ground_prompt_without_narration(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "arch.md").write_text(
        "The checkout service owns the cart lock.\n", encoding="utf-8"
    )
    (tmp_path / "docgen.yaml").write_text(
        yaml.dump(
            {
                "repo_root": ".",
                "segments": {"all": ["1"]},
                "manim_scene_generation": {"context": {"paths": ["docs/arch.md"]}},
            }
        ),
        encoding="utf-8",
    )
    cfg = Config.from_yaml(tmp_path / "docgen.yaml")
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="clean diagram of the checkout service",
    )
    seen: list[str] = []
    generate_images_for_spec(cfg, spec, image_fn=lambda p: seen.append(p) or _PNG_BYTES)
    assert seen
    assert "checkout service" in seen[0]
    assert "cart lock" in seen[0]


def test_ocr_invented_text_deletes_asset(cfg: Config) -> None:
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="clean diagram of the bootstrap pipeline",
    )
    cfg.narration_dir.mkdir(parents=True, exist_ok=True)
    (cfg.narration_dir / "1.md").write_text(
        "The bootstrap pipeline seeds the cluster.\n", encoding="utf-8"
    )
    with pytest.raises(ImageGenerationError, match="pixel alignment"):
        generate_images_for_spec(
            cfg,
            spec,
            image_fn=lambda p: _PNG_BYTES,
            ocr_fn=lambda _path: "WidgetX Orchestrator console",
        )
    assert not (cfg.base_dir / "images" / "arch.png").exists()


def test_vision_fail_retries_then_keeps_pass(cfg: Config) -> None:
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="clean diagram of the bootstrap pipeline",
    )
    cfg.narration_dir.mkdir(parents=True, exist_ok=True)
    (cfg.narration_dir / "1.md").write_text(
        "The bootstrap pipeline seeds the cluster.\n", encoding="utf-8"
    )
    seen: list[str] = []
    reviews = iter(
        [
            ImageReviewResult(False, "shows a generic city skyline"),
            ImageReviewResult(True, "now shows the bootstrap pipeline"),
        ]
    )

    def _review(*_a: object, **_k: object) -> ImageReviewResult:
        return next(reviews)

    generate_images_for_spec(
        cfg,
        spec,
        image_fn=lambda p: seen.append(p) or _PNG_BYTES,
        review_fn=_review,
        ocr_fn=lambda _path: "",
    )
    assert len(seen) == 2
    assert "PIXEL REVIEW FAILED" in seen[1]
    assert (cfg.base_dir / "images" / "arch.png").read_bytes() == _PNG_BYTES


def test_vision_fail_exhausted_deletes_asset(cfg: Config) -> None:
    spec = _write_spec(
        cfg.animations_dir / "specs" / "01-x.scene.yaml",
        prompt="clean diagram of the bootstrap pipeline",
    )
    cfg.narration_dir.mkdir(parents=True, exist_ok=True)
    (cfg.narration_dir / "1.md").write_text(
        "The bootstrap pipeline seeds the cluster.\n", encoding="utf-8"
    )
    with pytest.raises(ImageGenerationError, match="vision review FAIL"):
        generate_images_for_spec(
            cfg,
            spec,
            image_fn=lambda p: _PNG_BYTES,
            review_fn=lambda *_a, **_k: ImageReviewResult(False, "wrong subject"),
            ocr_fn=lambda _path: "",
        )
    assert not (cfg.base_dir / "images" / "arch.png").exists()


def test_build_aligned_image_prompt_includes_corpus_and_label() -> None:
    out = build_aligned_image_prompt(
        "clean diagram of the bootstrap pipeline",
        corpus_text="The bootstrap pipeline seeds the cluster.",
        label="bootstrap",
    )
    assert "bootstrap pipeline" in out
    assert "On-screen timing label" in out
    assert "Illustration request:" in out


def test_cli_image_generate_all_fails_when_manim_has_no_specs(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from docgen.cli import main

    raw = {
        "dirs": {"animations": "animations"},
        "segments": {"all": ["01"], "default": ["01"]},
        "visual_map": {"01": {"type": "manim", "scene": "DemoScene"}},
    }
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "animations").mkdir()
    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(p), "image-generate", "--all"])
    assert result.exit_code != 0
    assert "scene-spec-generate" in result.output or "no *.scene.yaml" in result.output
