"""Tests for docgen.validate — freeze ratio, blank frames, compose guard.

These tests generate synthetic videos with cv2/numpy so they don't
depend on any external recordings or tesseract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from docgen.compose import ComposeError, Composer
from docgen.config import Config
from docgen.validate import Validator, _sample_frames


# ── Helpers: create synthetic test videos ─────────────────────────────

def _make_video(
    path: Path,
    duration_sec: float = 10.0,
    fps: int = 30,
    width: int = 320,
    height: int = 240,
    frames_fn=None,
) -> Path:
    """Create a synthetic MP4.  *frames_fn(frame_idx, total)* returns a BGR numpy array."""
    total = int(duration_sec * fps)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))

    for i in range(total):
        if frames_fn:
            frame = frames_fn(i, total, width, height)
        else:
            frame = np.full((height, width, 3), 128, dtype=np.uint8)
        writer.write(frame)

    writer.release()
    return path


def _all_black(i, total, w, h):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _all_white(i, total, w, h):
    return np.full((h, w, 3), 255, dtype=np.uint8)


def _static_gray(i, total, w, h):
    """Every frame identical — 100% frozen."""
    return np.full((h, w, 3), 100, dtype=np.uint8)


def _half_then_black(i, total, w, h):
    """First half has changing content, second half is black."""
    if i < total // 2:
        frame = np.full((h, w, 3), 60 + (i % 180), dtype=np.uint8)
        cv2.putText(frame, f"f{i}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        return frame
    return np.zeros((h, w, 3), dtype=np.uint8)


def _changing_content(i, total, w, h):
    """Every frame is visibly different — 0% frozen, never dark."""
    intensity = 80 + int((i / total) * 150)
    frame = np.full((h, w, 3), intensity, dtype=np.uint8)
    cv2.putText(frame, f"Frame {i}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


def _mostly_active_small_freeze(i, total, w, h):
    """90% changing, last 10% frozen — should pass."""
    if i < int(total * 0.9):
        return _changing_content(i, total, w, h)
    return np.full((h, w, 3), 42, dtype=np.uint8)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def cfg_dir(tmp_path):
    """Set up a minimal docgen config directory."""
    cfg = {
        "segments": {"default": ["01"], "all": ["01"]},
        "segment_names": {"01": "01-test"},
        "visual_map": {"01": {"type": "vhs", "source": "01-test.mp4"}},
        "validation": {"max_drift_sec": 2.75, "max_freeze_ratio": 0.25},
    }
    (tmp_path / "docgen.yaml").write_text(yaml.dump(cfg), encoding="utf-8")
    for d in ("narration", "audio", "recordings", "terminal/rendered", "animations"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def config(cfg_dir):
    return Config.from_yaml(cfg_dir / "docgen.yaml")


# ── _sample_frames ────────────────────────────────────────────────────

class TestSampleFrames:
    def test_samples_entire_video(self, tmp_path):
        vid = _make_video(tmp_path / "test.mp4", duration_sec=10.0)
        samples = _sample_frames(vid, interval_sec=2.0)
        timestamps = [ts for ts, _ in samples]
        assert len(timestamps) >= 5
        assert timestamps[0] == pytest.approx(0.0, abs=0.1)
        assert timestamps[-1] >= 9.0, "Must sample near the end of the video"

    def test_short_video(self, tmp_path):
        vid = _make_video(tmp_path / "short.mp4", duration_sec=1.0)
        samples = _sample_frames(vid, interval_sec=2.0)
        assert len(samples) >= 1

    def test_nonexistent_file(self, tmp_path):
        samples = _sample_frames(tmp_path / "missing.mp4")
        assert samples == []


# ── Freeze ratio ──────────────────────────────────────────────────────

class TestFreezeRatio:
    def test_all_static_fails(self, config, cfg_dir):
        """A video where every frame is identical has 100% trailing freeze."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_static_gray)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_freeze_ratio(vid, samples)
        assert not result.passed, f"Static video should fail: {result.details}"

    def test_changing_content_passes(self, config, cfg_dir):
        """A video with every frame different has no trailing freeze."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_changing_content)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_freeze_ratio(vid, samples)
        assert result.passed, f"Active video should pass: {result.details}"

    def test_small_trailing_freeze_passes(self, config, cfg_dir):
        """10% frozen at the end is under 25% threshold."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10,
                          frames_fn=_mostly_active_small_freeze)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_freeze_ratio(vid, samples)
        assert result.passed, f"Small trailing freeze should pass: {result.details}"

    def test_long_trailing_freeze_fails(self, config, cfg_dir):
        """50% frozen tail exceeds 25% threshold."""
        def half_frozen_tail(i, total, w, h):
            if i < total // 2:
                return _changing_content(i, total, w, h)
            return np.full((h, w, 3), 80, dtype=np.uint8)

        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=half_frozen_tail)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_freeze_ratio(vid, samples)
        assert not result.passed, f"Long trailing freeze should fail: {result.details}"

    def test_interior_freeze_ignored(self, config, cfg_dir):
        """Freeze in the MIDDLE (not at the end) should not be penalised."""
        def freeze_in_middle(i, total, w, h):
            third = total // 3
            if i < third:
                return _changing_content(i, total, w, h)
            elif i < 2 * third:
                return np.full((h, w, 3), 80, dtype=np.uint8)
            else:
                return _changing_content(i, total, w, h)

        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=freeze_in_middle)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_freeze_ratio(vid, samples)
        assert result.passed, f"Interior freeze should pass: {result.details}"

    def test_respects_config_threshold(self, cfg_dir):
        """A looser threshold should let borderline videos pass."""
        cfg_raw = yaml.safe_load((cfg_dir / "docgen.yaml").read_text())
        cfg_raw["validation"]["max_freeze_ratio"] = 1.0
        (cfg_dir / "docgen.yaml").write_text(yaml.dump(cfg_raw))

        config = Config.from_yaml(cfg_dir / "docgen.yaml")
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_static_gray)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_freeze_ratio(vid, samples)
        assert result.passed, "100% threshold should pass even a static video"


# ── Blank / dark frames ──────────────────────────────────────────────

class TestBlankFrames:
    def test_all_black_fails(self, config, cfg_dir):
        """A completely black video must fail the blank check."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_all_black)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_blank_frames(vid, samples)
        assert not result.passed, f"All-black video should fail: {result.details}"

    def test_all_white_passes(self, config, cfg_dir):
        """A white video is not dark — should pass."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_all_white)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_blank_frames(vid, samples)
        assert result.passed, f"White video should pass: {result.details}"

    def test_half_black_fails(self, config, cfg_dir):
        """Second half going black exceeds 15% dark threshold."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_half_then_black)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_blank_frames(vid, samples)
        assert not result.passed, f"Half-black video should fail: {result.details}"

    def test_normal_content_passes(self, config, cfg_dir):
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_changing_content)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_blank_frames(vid, samples)
        assert result.passed

    def test_dark_ranges_reported(self, config, cfg_dir):
        """Blank check should report the time ranges that are dark."""
        vid = _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_half_then_black)
        v = Validator(config)
        samples = _sample_frames(vid)
        result = v._check_blank_frames(vid, samples)
        has_range_info = any("Dark ranges:" in d for d in result.details)
        assert has_range_info, f"Should report dark ranges: {result.details}"


# ── Compose guard ─────────────────────────────────────────────────────

class TestComposeGuard:
    def test_check_freeze_ratio_math(self, config):
        c = Composer(config)
        assert c.check_freeze_ratio(80.0, 80.0) == pytest.approx(0.0)
        assert c.check_freeze_ratio(80.0, 40.0) == pytest.approx(0.5)
        assert c.check_freeze_ratio(80.0, 20.0) == pytest.approx(0.75)
        assert c.check_freeze_ratio(100.0, 0.0) == pytest.approx(1.0)
        assert c.check_freeze_ratio(0.0, 50.0) == pytest.approx(0.0)

    def test_compose_rejects_short_video(self, config, cfg_dir):
        """Compose in strict mode should raise when video is way shorter than audio."""
        audio = cfg_dir / "audio" / "01-test.mp3"
        video = cfg_dir / "terminal" / "rendered" / "01-test.mp4"

        _make_video(video, duration_sec=10.0, frames_fn=_changing_content)
        _make_silent_audio(audio, duration_sec=80.0)

        c = Composer(config)
        with pytest.raises(ComposeError, match="FREEZE GUARD"):
            c._compose_simple("01", video, strict=True)

    def test_compose_allows_matching_durations(self, config, cfg_dir):
        """Compose should succeed when video roughly matches audio."""
        audio = cfg_dir / "audio" / "01-test.mp3"
        video = cfg_dir / "terminal" / "rendered" / "01-test.mp4"

        _make_video(video, duration_sec=75.0, frames_fn=_changing_content)
        _make_silent_audio(audio, duration_sec=80.0)

        c = Composer(config)
        result = c._compose_simple("01", video, strict=True)
        assert result is True

    def test_compose_nonstrict_warns(self, config, cfg_dir, capsys):
        """Non-strict mode prints a warning but doesn't raise."""
        audio = cfg_dir / "audio" / "01-test.mp3"
        video = cfg_dir / "terminal" / "rendered" / "01-test.mp4"

        _make_video(video, duration_sec=10.0, frames_fn=_changing_content)
        _make_silent_audio(audio, duration_sec=80.0)

        c = Composer(config)
        c._compose_simple("01", video, strict=False)
        captured = capsys.readouterr()
        assert "FREEZE GUARD" in captured.out or "WARNING" in captured.out


# ── Integration: validate_segment catches frozen video ────────────────

class TestValidateSegmentIntegration:
    def test_frozen_video_is_soft_warning(self, config, cfg_dir):
        """Static video flags freeze_ratio but pre-push treats it as a warning."""
        _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_static_gray)
        v = Validator(config)
        report = v.validate_segment("01")
        freeze_checks = [c for c in report["checks"] if c["name"] == "freeze_ratio"]
        assert freeze_checks, "freeze_ratio check must be present"
        assert not freeze_checks[0]["passed"], "Static video must flag freeze check"

    def test_black_video_detected(self, config, cfg_dir):
        """Full validate_segment should fail on a black video."""
        _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_all_black)
        v = Validator(config)
        report = v.validate_segment("01")
        blank_checks = [c for c in report["checks"] if c["name"] == "blank_frames"]
        assert blank_checks, "blank_frames check must be present"
        assert not blank_checks[0]["passed"], "Black video must fail blank check"

    def test_good_video_passes(self, config, cfg_dir):
        """A video with changing content should pass all frame checks."""
        _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_changing_content)
        v = Validator(config)
        report = v.validate_segment("01")

        frame_checks = {c["name"]: c for c in report["checks"]
                        if c["name"] in ("freeze_ratio", "blank_frames")}
        for name, check in frame_checks.items():
            assert check["passed"], f"{name} should pass: {check['details']}"

    def test_half_black_fails_pre_push(self, config, cfg_dir):
        """Pre-push should exit non-zero when video has black sections (hard fail)."""
        _make_video(cfg_dir / "recordings" / "01-test.mp4", 10, frames_fn=_half_then_black)
        v = Validator(config)
        with pytest.raises(SystemExit):
            v.run_pre_push()

    def test_static_video_does_not_fail_pre_push(self, config, cfg_dir):
        """freeze_ratio is a soft check — static (non-black) video only warns."""
        vid = cfg_dir / "recordings" / "01-test.mp4"
        vid_raw = cfg_dir / "recordings" / "01-test-raw.mp4"
        _make_video(vid_raw, 10, frames_fn=_static_gray)
        audio = cfg_dir / "recordings" / "01-test-audio.mp3"
        _make_silent_audio(audio, 10)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(vid_raw), "-i", str(audio),
             "-c:v", "copy", "-c:a", "aac", "-shortest", str(vid)],
            capture_output=True, timeout=30,
        )
        (cfg_dir / "narration" / "01-test.md").write_text("Narration text here.\n")
        v = Validator(config)
        v.run_pre_push()  # should NOT raise


# ── Helper to create silent audio ─────────────────────────────────────

def _make_silent_audio(path: Path, duration_sec: float = 10.0) -> Path:
    """Create a silent MP3 using ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration_sec),
            "-c:a", "libmp3lame", "-b:a", "32k",
            str(path),
        ],
        capture_output=True, timeout=30,
    )
    return path
