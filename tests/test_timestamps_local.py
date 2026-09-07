"""Tests for the ``timestamps`` engine selection and local (no-Whisper) extraction."""

from __future__ import annotations

import json

import pytest
import yaml

import docgen.align as align_module
from docgen.config import Config
from docgen.timestamps import TimestampExtractor


@pytest.fixture
def cfg(tmp_path) -> Config:
    raw = {
        "segments": {"all": ["01"]},
        "segment_names": {"01": "01-x"},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
    (tmp_path / "audio").mkdir()
    (tmp_path / "narration").mkdir()
    return Config.from_yaml(tmp_path / "docgen.yaml")


def _fake_audio_env(monkeypatch, duration: float = 6.0) -> None:
    """Bypass ffprobe/ffmpeg: fixed duration, one mid-audio silence."""
    monkeypatch.setattr(align_module, "probe_duration", lambda p: duration)
    monkeypatch.setattr(
        align_module,
        "detect_speech_intervals",
        lambda p, d, **kw: [(0.0, d / 2 - 0.3), (d / 2 + 0.3, d)],
    )


class TestResolveEngine:
    def test_default_is_local(self, cfg) -> None:
        assert TimestampExtractor(cfg).resolve_engine() == "local"

    def test_config_engine_respected(self, tmp_path) -> None:
        (tmp_path / "docgen.yaml").write_text(
            yaml.dump({"timestamps": {"engine": "whisper"}}), encoding="utf-8"
        )
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        assert TimestampExtractor(cfg).resolve_engine() == "whisper"

    def test_cli_override_wins(self, cfg) -> None:
        assert TimestampExtractor(cfg).resolve_engine("whisper") == "whisper"

    def test_unknown_engine_fails_loud(self, cfg) -> None:
        with pytest.raises(RuntimeError, match="unknown engine"):
            TimestampExtractor(cfg).resolve_engine("gibberish")


class TestExtractLocal:
    def test_writes_whisper_shaped_timing_json(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text(
            "# Heading\n\nAlpha begins the story. Beta ends it.\n", encoding="utf-8"
        )
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")

        TimestampExtractor(cfg).extract_all()

        timing = json.loads((cfg.animations_dir / "timing.json").read_text(encoding="utf-8"))
        block = timing["01-x"]
        assert set(block.keys()) == {"text", "segments", "words"}
        assert [s["text"] for s in block["segments"]] == [
            "Alpha begins the story.",
            "Beta ends it.",
        ]
        # Two sentences, two detected speech intervals → 1:1 mapping.
        assert block["segments"][1]["start"] == pytest.approx(3.3)
        assert block["words"][0]["word"] == "Alpha"

    def test_missing_narration_fails_loud(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        with pytest.raises(RuntimeError, match="narration/01-x.md"):
            TimestampExtractor(cfg).extract_all()

    def test_markdown_is_stripped_before_alignment(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text(
            "# Title skipped\n\n**Bold** words spoken here. Second `code` sentence.\n",
            encoding="utf-8",
        )
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")

        TimestampExtractor(cfg).extract_all()

        timing = json.loads((cfg.animations_dir / "timing.json").read_text(encoding="utf-8"))
        words = [w["word"] for w in timing["01-x"]["words"]]
        assert "Bold" in words
        assert "#" not in " ".join(words)
        assert "**Bold**" not in words


    def test_no_mp3s_fails_when_segments_listed(self, cfg) -> None:
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"keep": true}\n', encoding="utf-8")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match="missing audio"):
            TimestampExtractor(cfg).extract_all()
        assert json.loads(out.read_text(encoding="utf-8")) == {"keep": True}

    def test_empty_segments_all_leaves_existing_timing_json(self, tmp_path) -> None:
        (tmp_path / "docgen.yaml").write_text(
            yaml.dump({"segments": {"all": []}}), encoding="utf-8"
        )
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"keep": true}\n', encoding="utf-8")
        TimestampExtractor(cfg).extract_all()
        assert json.loads(out.read_text(encoding="utf-8")) == {"keep": True}

    def test_heading_only_narration_fails_loud(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("# Title only\n---\n*(pause)*\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match="no spoken text"):
            TimestampExtractor(cfg).extract_all()

    def test_zero_duration_audio_fails_loud(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch, duration=0.0)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins the story.\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        from docgen.align import AlignmentError

        with pytest.raises(AlignmentError, match="duration"):
            TimestampExtractor(cfg).extract_all()

    def test_orphan_short_id_mp3_is_not_used(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins. Beta ends.\n", encoding="utf-8")
        (cfg.audio_dir / "01.mp3").write_bytes(b"orphan")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match="01-x.mp3"):
            TimestampExtractor(cfg).extract_all()

    def test_does_not_wipe_timing_when_a_listed_segment_is_missing(
        self, tmp_path, monkeypatch
    ) -> None:
        _fake_audio_env(monkeypatch)
        raw = {
            "segments": {"all": ["01", "02"]},
            "segment_names": {"01": "01-a", "02": "02-b"},
        }
        (tmp_path / "docgen.yaml").write_text(yaml.dump(raw), encoding="utf-8")
        (tmp_path / "audio").mkdir()
        (tmp_path / "narration").mkdir()
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        (cfg.narration_dir / "01-a.md").write_text("Hello world.\n", encoding="utf-8")
        (cfg.audio_dir / "01-a.mp3").write_bytes(b"fake")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"02-b": {"text": "keep"}}\n', encoding="utf-8")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match="02"):
            TimestampExtractor(cfg).extract_all()
        assert json.loads(out.read_text(encoding="utf-8")) == {"02-b": {"text": "keep"}}

    def test_whisper_engine_fails_fast_without_stt(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from docgen.ai_client import AIError

        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        (tmp_path / "docgen.yaml").write_text(
            yaml.dump({"timestamps": {"engine": "whisper"}, "ai": {"provider": "openai"}}),
            encoding="utf-8",
        )
        (tmp_path / "audio").mkdir()
        (tmp_path / "audio" / "01-x.mp3").write_bytes(b"fake")
        cfg = Config.from_yaml(tmp_path / "docgen.yaml")
        with pytest.raises(AIError, match="whisper"):
            TimestampExtractor(cfg).extract_all()


    def test_extract_all_preserves_extra_timing_stems(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins the story.\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({
                "legacy-stem": {
                    "text": "keep-me",
                    "words": [{"word": "x", "start": 0.0, "end": 0.1}],
                }
            }),
            encoding="utf-8",
        )
        TimestampExtractor(cfg).extract_all()
        timing = json.loads(out.read_text(encoding="utf-8"))
        assert timing["legacy-stem"]["text"] == "keep-me"
        assert "01-x" in timing
        assert timing["01-x"]["words"]


    def test_extract_all_rejects_corrupt_timing_json(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins the story.\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("{not-json", encoding="utf-8")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match="not valid JSON"):
            TimestampExtractor(cfg).extract_all()
        assert out.read_text(encoding="utf-8") == "{not-json"


    def test_extract_all_rejects_non_object_timing_json(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins the story.\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("[1, 2]\n", encoding="utf-8")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match="JSON object"):
            TimestampExtractor(cfg).extract_all()
        assert out.read_text(encoding="utf-8") == "[1, 2]\n"


    def test_extract_all_rejects_non_object_timing_stem(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins the story.\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"legacy-stem": ["not", "an", "object"]}) + "\n"
        out.write_text(payload, encoding="utf-8")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match=r"timing.json\['legacy-stem'\] must be a JSON object"):
            TimestampExtractor(cfg).extract_all()
        assert out.read_text(encoding="utf-8") == payload


    def test_load_bundle_timing_rejects_scalar_stems(self, cfg) -> None:
        from docgen.timestamps import TimestampError, load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cases = (
            ({"01-x": "whisper-dump"}, "str"),
            ({"01-x": 3}, "int"),
            ({"01-x": None}, "null"),
        )
        for payload, kind in cases:
            out.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(TimestampError, match=rf"timing.json\['01-x'\] must be a JSON object, not {kind}"):
                load_bundle_timing(cfg)

    def test_load_bundle_timing_accepts_object_stems(self, cfg) -> None:
        from docgen.timestamps import load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"01-x": {"text": "ok", "words": [], "segments": []}}
        out.write_text(json.dumps(payload), encoding="utf-8")
        assert load_bundle_timing(cfg) == payload

    def test_load_bundle_timing_accepts_missing_or_null_inner_lists(self, cfg) -> None:
        from docgen.timestamps import load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"01-x": {"text": "ok", "words": None}, "legacy": {"text": "keep"}}
        out.write_text(json.dumps(payload), encoding="utf-8")
        assert load_bundle_timing(cfg) == payload

    def test_load_bundle_timing_rejects_non_array_inner_lists(self, cfg) -> None:
        from docgen.timestamps import TimestampError, load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cases = (
            ({"01-x": {"words": "not-a-list"}}, r"timing.json\['01-x'\].words must be a JSON array, not str"),
            ({"01-x": {"words": {}}}, r"timing.json\['01-x'\].words must be a JSON array, not dict"),
            ({"01-x": {"segments": 3}}, r"timing.json\['01-x'\].segments must be a JSON array, not int"),
        )
        for payload, match in cases:
            out.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(TimestampError, match=match):
                load_bundle_timing(cfg)

    def test_load_bundle_timing_rejects_non_object_inner_items(self, cfg) -> None:
        from docgen.timestamps import TimestampError, load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cases = (
            (
                {"01-x": {"words": ["hello"]}},
                r"timing.json\['01-x'\].words\[0\] must be a JSON object, not str",
            ),
            (
                {"01-x": {"segments": [1]}},
                r"timing.json\['01-x'\].segments\[0\] must be a JSON object, not int",
            ),
            (
                {"01-x": {"words": [None]}},
                r"timing.json\['01-x'\].words\[0\] must be a JSON object, not null",
            ),
        )
        for payload, match in cases:
            out.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(TimestampError, match=match):
                load_bundle_timing(cfg)

    def test_extract_all_rejects_non_array_words_without_rewrite(self, cfg, monkeypatch) -> None:
        _fake_audio_env(monkeypatch)
        (cfg.narration_dir / "01-x.md").write_text("Alpha begins the story.\n", encoding="utf-8")
        (cfg.audio_dir / "01-x.mp3").write_bytes(b"fake-mp3")
        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"legacy-stem": {"words": "corrupt"}}) + "\n"
        out.write_text(payload, encoding="utf-8")
        from docgen.timestamps import TimestampError

        with pytest.raises(TimestampError, match=r"timing.json\['legacy-stem'\].words must be a JSON array"):
            TimestampExtractor(cfg).extract_all()
        assert out.read_text(encoding="utf-8") == payload

    def test_load_bundle_timing_rejects_non_numeric_start_end(self, cfg) -> None:
        from docgen.timestamps import TimestampError, load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cases = (
            (
                {"01-x": {"words": [{"word": "hi", "end": 0.1}]}},
                r"timing.json\['01-x'\].words\[0\].start must be a JSON number, not missing",
            ),
            (
                {"01-x": {"words": [{"word": "hi", "start": None, "end": 0.1}]}},
                r"timing.json\['01-x'\].words\[0\].start must be a JSON number, not null",
            ),
            (
                {"01-x": {"words": [{"word": "hi", "start": True, "end": 0.1}]}},
                r"timing.json\['01-x'\].words\[0\].start must be a JSON number, not bool",
            ),
            (
                {"01-x": {"words": [{"word": "hi", "start": "0.0", "end": 0.1}]}},
                r"timing.json\['01-x'\].words\[0\].start must be a JSON number, not str",
            ),
            (
                {"01-x": {"segments": [{"text": "hi", "start": 0.0}]}},
                r"timing.json\['01-x'\].segments\[0\].end must be a JSON number, not missing",
            ),
        )
        for payload, match in cases:
            out.write_text(json.dumps(payload), encoding="utf-8")
            with pytest.raises(TimestampError, match=match):
                load_bundle_timing(cfg)

    def test_load_bundle_timing_accepts_numeric_start_end(self, cfg) -> None:
        from docgen.timestamps import load_bundle_timing

        out = cfg.animations_dir / "timing.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "01-x": {
                "words": [{"word": "hi", "start": 0, "end": 0.25}],
                "segments": [{"text": "hi", "start": 0.0, "end": 1}],
            }
        }
        out.write_text(json.dumps(payload), encoding="utf-8")
        assert load_bundle_timing(cfg) == payload

