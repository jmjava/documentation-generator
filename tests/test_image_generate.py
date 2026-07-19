"""Tests for docgen.image_generate — spec-driven OpenAI image assets (fake image fn)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from docgen.config import Config
from docgen.image_generate import (
    ImageGenerationError,
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


def test_no_specs_dir_is_noop(cfg: Config) -> None:
    assert spec_files_for_bundle(cfg) == []
    assert generate_missing_images_for_bundle(cfg, image_fn=lambda p: _PNG_BYTES) == []
