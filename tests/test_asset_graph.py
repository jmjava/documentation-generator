"""Tests for wizard asset freshness graph + rebuild-from-here cascade."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from docgen.asset_graph import (
    cascade_steps,
    segment_asset_report,
    segment_step_statuses,
)
from docgen.config import Config
from docgen.wizard import create_app, generate_narration_via_llm


def test_cascade_steps_default_uses_retime() -> None:
    assert cascade_steps("tts") == [
        "tts",
        "timestamps",
        "scene-retime",
        "manim",
        "compose",
        "validate",
    ]
    assert cascade_steps("scene-retime")[0] == "scene-retime"
    assert "scene-spec" not in cascade_steps("timestamps")


def test_cascade_steps_scene_spec_tail() -> None:
    assert cascade_steps("scene-spec") == [
        "scene-spec",
        "manim",
        "compose",
        "validate",
    ]


def test_cascade_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown"):
        cascade_steps("nope")


def _bundle(tmp_path: Path) -> Config:
    raw = {
        "segments": {"all": ["01"], "default": ["01"]},
        "segment_names": {"01": "01-demo"},
        "visual_map": {
            "01": {"type": "manim", "scene": "DemoScene", "source": "DemoScene.mp4"}
        },
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "recordings": "recordings",
        },
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    for d in ("narration", "audio", "animations", "recordings", "animations/specs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(tmp_path / "docgen.yaml")


def test_segment_statuses_missing_then_fresh(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    statuses = {s.step: s for s in segment_step_statuses(cfg, "01")}
    assert statuses["tts"].status == "missing"
    assert statuses["timestamps"].status == "missing"

    narr = cfg.narration_dir / "01-demo.md"
    narr.write_text("Hello world.\n", encoding="utf-8")
    time.sleep(0.02)
    audio = cfg.audio_dir / "01-demo.mp3"
    audio.write_bytes(b"fake")
    time.sleep(0.02)
    (cfg.animations_dir / "timing.json").write_text(
        json.dumps({"01-demo": {"words": [{"word": "Hello", "start": 0, "end": 0.2}]}}),
        encoding="utf-8",
    )
    time.sleep(0.02)
    spec = cfg.animations_dir / "specs" / "01-demo.scene.yaml"
    spec.write_text("segment_id: '01'\n", encoding="utf-8")
    time.sleep(0.02)
    visual = cfg.animations_dir / "DemoScene.mp4"
    visual.write_bytes(b"vid")
    time.sleep(0.02)
    rec = cfg.recordings_dir / "01-demo.mp4"
    rec.write_bytes(b"rec")

    statuses = {s.step: s for s in segment_step_statuses(cfg, "01")}
    assert statuses["tts"].status == "fresh"
    assert statuses["timestamps"].status == "fresh"
    assert statuses["scene-retime"].status == "fresh"
    assert statuses["manim"].status == "fresh"
    assert statuses["compose"].status == "fresh"


def test_stale_when_narration_newer_than_audio(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    audio = cfg.audio_dir / "01-demo.mp3"
    audio.write_bytes(b"old")
    narr = cfg.narration_dir / "01-demo.md"
    narr.write_text("newer narration\n", encoding="utf-8")
    # Force a clear mtime gap beyond the 1s freshness tolerance.
    now = time.time()
    import os

    os.utime(audio, (now - 10, now - 10))
    os.utime(narr, (now, now))
    statuses = {s.step: s for s in segment_step_statuses(cfg, "01")}
    assert statuses["tts"].status == "stale"


def test_api_segments_includes_assets(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    (cfg.narration_dir / "01-demo.md").write_text("hi\n", encoding="utf-8")
    app = create_app(cfg)
    client = app.test_client()
    res = client.get("/api/segments")
    assert res.status_code == 200
    seg = res.get_json()["segments"][0]
    assert "assets" in seg
    steps = {s["step"] for s in seg["assets"]["steps"]}
    assert "tts" in steps
    assert "scene-retime" in steps

    assets = client.get("/api/segments/01/assets")
    assert assets.status_code == 200
    assert assets.get_json()["segment_id"] == "01"


def test_api_run_from_cascades_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _bundle(tmp_path)
    app = create_app(cfg)
    client = app.test_client()
    called: list[str] = []

    from docgen import compose, manim_runner, scene_retime, timestamps, validate

    monkeypatch.setattr(
        timestamps.TimestampExtractor,
        "resolve_engine",
        lambda self, e: "local",
    )
    monkeypatch.setattr(
        timestamps.TimestampExtractor,
        "extract_local",
        lambda self, mp3: called.append("timestamps")
        or {"words": [{"word": "hi", "start": 0, "end": 0.1}]},
    )
    monkeypatch.setattr(
        scene_retime,
        "list_scene_spec_paths",
        lambda cfg, segment_id=None: [
            tmp_path / "animations" / "specs" / "01-demo.scene.yaml"
        ],
    )
    monkeypatch.setattr(
        scene_retime,
        "retime_compile_spec",
        lambda cfg, path, dry_run=False: called.append("scene-retime")
        or {"path": path, "wrote": True},
    )
    monkeypatch.setattr(
        manim_runner.ManimRunner,
        "render",
        lambda self, scene=None: called.append("manim") or None,
    )
    monkeypatch.setattr(
        compose.Composer,
        "compose_segments",
        lambda self, ids: called.append("compose") or True,
    )
    monkeypatch.setattr(
        validate.Validator,
        "validate_segment",
        lambda self, sid: called.append("validate") or {"segment": sid, "checks": []},
    )
    monkeypatch.setattr(
        "docgen.manim_scene_support.sync_audio_tail_waits_in_scenes",
        lambda cfg: None,
    )

    (cfg.audio_dir / "01-demo.mp3").write_bytes(b"x")
    (cfg.animations_dir / "specs" / "01-demo.scene.yaml").write_text("x", encoding="utf-8")

    res = client.post("/api/run-from/timestamps/01", json={})
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["ok"] is True
    assert body["planned"][0] == "timestamps"
    assert "scene-retime" in body["planned"]
    assert "scene-spec" not in body["planned"]
    assert called == ["timestamps", "scene-retime", "manim", "compose", "validate"]


def test_revise_mode_includes_current_narration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _FakeMsg:
        content = "Revised script."

    class _FakeChoice:
        message = _FakeMsg()

    class _FakeResp:
        choices = [_FakeChoice()]

    class _FakeCompletions:
        def create(self, **kwargs):  # noqa: ANN003
            captured.update(kwargs)
            return _FakeResp()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr("openai.OpenAI", lambda: _FakeClient())

    out = generate_narration_via_llm(
        source_texts=["## File: a.md\nsource"],
        guidance="keep short",
        system_prompt="Write narration.",
        model="gpt-4o",
        segment_name="01-demo",
        revision_notes="Mention Flask",
        current_narration="Original line about pipelines.",
        mode="revise",
    )
    assert out == "Revised script."
    user = captured["messages"][1]["content"]
    assert "CURRENT NARRATION" in user
    assert "Original line about pipelines." in user
    assert "Mention Flask" in user
    assert "revising an existing" in captured["messages"][0]["content"].lower()


def test_revise_mode_requires_notes() -> None:
    with pytest.raises(ValueError, match="revision_notes"):
        generate_narration_via_llm(
            source_texts=[],
            guidance="",
            system_prompt="x",
            model="gpt-4o",
            segment_name="01",
            revision_notes="",
            current_narration="Hello",
            mode="revise",
        )


def test_api_generate_revise_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _bundle(tmp_path)
    (cfg.narration_dir / "01-demo.md").write_text("Old text.\n", encoding="utf-8")
    app = create_app(cfg)
    client = app.test_client()

    monkeypatch.setattr(
        "docgen.wizard.generate_narration_via_llm",
        lambda **kwargs: "New revised text.",
    )
    res = client.post(
        "/api/generate-narration",
        json={
            "segment_id": "01",
            "segment_name": "01-demo",
            "mode": "revise",
            "current_narration": "Old text.",
            "revision_notes": "Tighten the opening.",
            "source_paths": [],
        },
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["mode"] == "revise"
    assert "New revised text." in body["narration"]
    assert (cfg.narration_dir / "01-demo.md").read_text(encoding="utf-8").startswith(
        "New revised text."
    )


def test_segment_asset_report_lists_stale(tmp_path: Path) -> None:
    cfg = _bundle(tmp_path)
    report = segment_asset_report(cfg, "01")
    assert "tts" in report["stale_or_missing"]
    assert report["default_cascade"][2] == "scene-retime"
