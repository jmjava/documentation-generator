"""Tests for new compose.py features: quality-aware paths, stale VHS warnings."""

import time

import yaml

from docgen.compose import Composer
from docgen.config import Config


def _make_config(tmp_path, quality="720p30", warn_stale=True):
    cfg = {
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-test"},
        "visual_map": {"01": {"type": "manim", "source": "Scene01.mp4"}},
        "manim": {"quality": quality},
        "compose": {"warn_stale_vhs": warn_stale},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    for d in ("narration", "audio", "recordings", "terminal/rendered", "animations"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return Config.from_yaml(tmp_path / "docgen.yaml")


class TestQualityAwarePath:
    def test_finds_configured_quality(self, tmp_path):
        config = _make_config(tmp_path, quality="1080p30")
        base = tmp_path / "animations" / "media" / "videos" / "scenes"
        (base / "1080p30").mkdir(parents=True)
        (base / "1080p30" / "Scene01.mp4").write_text("fake")

        c = Composer(config)
        path = c._manim_path({"source": "Scene01.mp4"})
        assert "1080p30" in str(path)
        assert path.exists()

    def test_falls_back_to_other_quality(self, tmp_path):
        config = _make_config(tmp_path, quality="1080p30")
        base = tmp_path / "animations" / "media" / "videos" / "scenes"
        (base / "720p30").mkdir(parents=True)
        (base / "720p30" / "Scene01.mp4").write_text("fake")

        c = Composer(config)
        path = c._manim_path({"source": "Scene01.mp4"})
        assert "720p30" in str(path)
        assert path.exists()

    def test_checks_no_scenes_subdir(self, tmp_path):
        config = _make_config(tmp_path, quality="1080p30")
        base = tmp_path / "animations" / "media" / "videos"
        (base / "1080p30").mkdir(parents=True)
        (base / "1080p30" / "Scene01.mp4").write_text("fake")

        c = Composer(config)
        path = c._manim_path({"source": "Scene01.mp4"})
        assert path.exists()


class TestStaleVHSCheck:
    def test_warns_stale_tape(self, tmp_path, capsys):
        config = _make_config(tmp_path, warn_stale=True)
        rendered = tmp_path / "terminal" / "rendered" / "01-test.mp4"
        rendered.write_text("fake video")

        time.sleep(0.05)
        tape = tmp_path / "terminal" / "01-test.tape"
        tape.write_text("Set Shell bash\nType echo hello\nEnter\n")

        c = Composer(config)
        c._vhs_path({"source": "01-test.mp4"})

        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "newer" in captured.out

    def test_no_warning_when_disabled(self, tmp_path, capsys):
        config = _make_config(tmp_path, warn_stale=False)
        rendered = tmp_path / "terminal" / "rendered" / "01-test.mp4"
        rendered.write_text("fake video")

        time.sleep(0.05)
        tape = tmp_path / "terminal" / "01-test.tape"
        tape.write_text("Set Shell bash\nType echo hello\n")

        c = Composer(config)
        c._vhs_path({"source": "01-test.mp4"})

        captured = capsys.readouterr()
        assert "WARNING" not in captured.out

    def test_no_warning_when_rendered_is_newer(self, tmp_path, capsys):
        config = _make_config(tmp_path, warn_stale=True)
        tape = tmp_path / "terminal" / "01-test.tape"
        tape.write_text("Set Shell bash\nType echo hello\n")

        time.sleep(0.05)
        rendered = tmp_path / "terminal" / "rendered" / "01-test.mp4"
        rendered.write_text("fake video")

        c = Composer(config)
        c._vhs_path({"source": "01-test.mp4"})

        captured = capsys.readouterr()
        assert "WARNING" not in captured.out
