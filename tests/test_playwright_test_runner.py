"""Tests for docgen.playwright_test_runner."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from docgen.config import Config
from docgen.playwright_test_runner import PlaywrightTestRunner, RunResult


@pytest.fixture
def runner_config(tmp_path):
    """Config with playwright_test settings."""
    cfg_data = {
        "segments": {"all": ["01", "02"]},
        "visual_map": {
            "01": {"type": "manim", "source": "Scene.mp4"},
            "02": {
                "type": "playwright_test",
                "test": "tests/e2e/test_wizard.py::test_setup",
                "source": "test-results/videos/test_setup.webm",
                "trace": "test-results/traces/test_setup/trace.zip",
            },
        },
        "playwright_test": {
            "framework": "pytest",
            "test_dir": "tests/e2e",
            "video_dir": "test-results/videos",
            "trace_dir": "test-results/traces",
            "retain_on_failure": True,
        },
    }
    (tmp_path / ".git").mkdir()
    p = tmp_path / "docgen.yaml"
    p.write_text(yaml.dump(cfg_data), encoding="utf-8")
    return Config.from_yaml(p)


class TestPlaywrightTestRunner:
    def test_init(self, runner_config):
        runner = PlaywrightTestRunner(runner_config)
        assert runner._pt_cfg["framework"] == "pytest"

    def test_run_segment_tests_skips_non_playwright_test(self, runner_config):
        runner = PlaywrightTestRunner(runner_config)
        with patch.object(runner, "run_tests", return_value=[]) as mock_run:
            runner.run_segment_tests()
        mock_run.assert_called_once()

    def test_resolve_dirs(self, runner_config):
        runner = PlaywrightTestRunner(runner_config)
        test_dir = runner._resolve_test_dir()
        video_dir = runner._resolve_video_dir()
        trace_dir = runner._resolve_trace_dir()
        assert "tests/e2e" in str(test_dir) or "tests" in str(test_dir)
        assert "test-results/videos" in str(video_dir)
        assert "test-results/traces" in str(trace_dir)


class TestRunResultCls:
    def test_defaults(self):
        r = RunResult(test="test_foo.py")
        assert r.success is True
        assert r.video_path is None
        assert r.trace_path is None
        assert r.errors == []

    def test_with_errors(self):
        r = RunResult(test="test_foo.py", success=False, errors=["timeout"])
        assert not r.success
        assert r.errors == ["timeout"]
