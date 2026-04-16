"""Tests for docgen.playwright_sync — event-to-narration synchronization."""

from __future__ import annotations

import json

import pytest
import yaml

from docgen.config import Config
from docgen.playwright_sync import (
    AnchorMatch,
    PlaywrightSynchronizer,
    SpeedSegment,
    SyncResult,
)


@pytest.fixture
def sync_config(tmp_path):
    cfg_data = {
        "segments": {"all": ["01"]},
        "visual_map": {
            "01": {
                "type": "playwright_test",
                "test": "tests/e2e/test_setup.py",
                "source": "test-results/videos/test_setup.webm",
                "trace": "test-results/traces/trace.zip",
                "events": [
                    {"narration_anchor": "email", "action": "fill", "selector": "#email"},
                    {"narration_anchor": "submit", "action": "click", "selector": "button[type=submit]"},
                ],
            },
        },
        "playwright_test": {"min_speed_factor": 0.25, "max_speed_factor": 4.0},
    }
    for d in ("narration", "audio", "animations", "terminal", "recordings"):
        (tmp_path / d).mkdir()
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg_data), encoding="utf-8")
    return Config.from_yaml(p)


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------


class TestSyncResult:
    def test_to_dict(self):
        result = SyncResult(
            segment="01",
            strategy="stretch",
            anchors=[
                AnchorMatch(
                    event_idx=0, event_t=1.2, action="fill",
                    selector="#email", narration_t=2.0, narration_text="email",
                ),
            ],
            speed_segments=[
                SpeedSegment(
                    video_start=0.0, video_end=1.2,
                    narration_start=0.0, narration_end=2.0, factor=1.667,
                ),
            ],
        )
        d = result.to_dict()
        assert d["segment"] == "01"
        assert d["strategy"] == "stretch"
        assert len(d["anchors"]) == 1
        assert d["anchors"][0]["event_t"] == 1.2
        assert len(d["speed_segments"]) == 1
        assert d["speed_segments"][0]["factor"] == 1.667


# ---------------------------------------------------------------------------
# PlaywrightSynchronizer
# ---------------------------------------------------------------------------


class TestPlaywrightSynchronizer:
    def test_init(self, sync_config):
        syncer = PlaywrightSynchronizer(sync_config)
        assert syncer._min_speed == 0.25
        assert syncer._max_speed == 4.0

    def test_sync_with_events_and_timing(self, sync_config):
        """Full sync: events.json + timing.json → sync_map.json."""
        events = [
            {"t": 0.0, "action": "goto", "url": "http://localhost"},
            {"t": 1.2, "action": "fill", "selector": "#email", "value": "user@test.com"},
            {"t": 3.4, "action": "click", "selector": "button[type=submit]"},
        ]
        timing = {
            "01": {
                "text": "Now we fill in the email address and click submit",
                "segments": [{"start": 0, "end": 6.0, "text": "Now we fill in the email address and click submit"}],
                "words": [
                    {"start": 0.0, "end": 0.5, "word": "Now"},
                    {"start": 0.5, "end": 0.8, "word": "we"},
                    {"start": 0.8, "end": 1.2, "word": "fill"},
                    {"start": 1.2, "end": 1.5, "word": "in"},
                    {"start": 1.5, "end": 1.8, "word": "the"},
                    {"start": 1.8, "end": 2.5, "word": "email"},
                    {"start": 2.5, "end": 3.0, "word": "address"},
                    {"start": 3.0, "end": 3.3, "word": "and"},
                    {"start": 3.3, "end": 3.6, "word": "click"},
                    {"start": 3.6, "end": 4.2, "word": "submit"},
                ],
            },
        }

        anim_dir = sync_config.animations_dir
        (anim_dir / "01-events.json").write_text(json.dumps(events), encoding="utf-8")
        (anim_dir / "timing.json").write_text(json.dumps(timing), encoding="utf-8")

        syncer = PlaywrightSynchronizer(sync_config)
        results = syncer.sync()

        assert len(results) == 1
        r = results[0]
        assert r.segment == "01"
        assert len(r.anchors) == 2
        assert r.anchors[0].action == "fill"
        assert r.anchors[1].action == "click"
        assert len(r.speed_segments) >= 2

        sync_map_path = anim_dir / "01-sync_map.json"
        assert sync_map_path.exists()

    def test_sync_no_events(self, sync_config):
        timing = {"01": {"text": "test", "words": [], "segments": []}}
        (sync_config.animations_dir / "timing.json").write_text(
            json.dumps(timing), encoding="utf-8"
        )

        syncer = PlaywrightSynchronizer(sync_config)
        results = syncer.sync()
        assert len(results) == 0

    def test_sync_dry_run_no_write(self, sync_config):
        events = [{"t": 0.0, "action": "goto", "url": "http://localhost"}]
        timing = {
            "01": {
                "text": "test", "segments": [],
                "words": [{"start": 0.0, "end": 1.0, "word": "test"}],
            }
        }
        anim_dir = sync_config.animations_dir
        (anim_dir / "01-events.json").write_text(json.dumps(events), encoding="utf-8")
        (anim_dir / "timing.json").write_text(json.dumps(timing), encoding="utf-8")

        syncer = PlaywrightSynchronizer(sync_config)
        results = syncer.sync(dry_run=True)
        assert len(results) == 1
        assert not (anim_dir / "01-sync_map.json").exists()


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    @pytest.mark.parametrize(
        "event,expected_has",
        [
            ({"selector": "#email"}, "email"),
            ({"selector": "button[type=submit]"}, "submit"),
            ({"url": "http://localhost/dashboard"}, "dashboard"),
            ({"selector": "[data-testid=save-btn]"}, "save"),
            ({"value": "hello world testing"}, "hello"),
        ],
    )
    def test_extract_keywords(self, event, expected_has):
        keywords = PlaywrightSynchronizer._extract_keywords(event)
        lower_kws = [k.lower() for k in keywords]
        assert any(expected_has in kw for kw in lower_kws), f"{keywords} should contain '{expected_has}'"


# ---------------------------------------------------------------------------
# Speed factor clamping
# ---------------------------------------------------------------------------


class TestSpeedClamping:
    def test_factor_clamped_to_range(self, sync_config):
        syncer = PlaywrightSynchronizer(sync_config)
        events = [
            {"t": 0.0, "action": "goto", "url": "/"},
            {"t": 0.1, "action": "click", "selector": "#btn"},
        ]
        timing_entry = {
            "words": [{"start": 0, "end": 100, "word": "test"}],
            "segments": [{"start": 0, "end": 100, "text": "test"}],
        }
        result = syncer._sync_one("01", events, timing_entry, [], "stretch")
        for seg in result.speed_segments:
            assert seg.factor >= 0.25
            assert seg.factor <= 4.0
