"""Tests for docgen.scenario — YAML scenario loader and saver."""

from __future__ import annotations

from pathlib import Path

import yaml

from docgen.scenario import (
    AppConfig,
    Scenario,
    ScenarioStep,
    load_scenario,
    save_scenario,
)


# ── load_scenario ────────────────────────────────────────────────────


class TestLoadScenario:
    def test_loads_basic_scenario(self, tmp_path: Path):
        data = {
            "app": {
                "name": "TestApp",
                "base_url": "http://localhost:3000",
                "viewport": {"width": 1280, "height": 720},
                "ready_selector": "#app",
                "ready_wait_ms": 5000,
            },
            "steps": [
                {
                    "id": "step1",
                    "narration": "Click the button",
                    "browser": True,
                    "demo": True,
                    "visual_type": "playwright",
                    "act": [{"click": {"selector": "#btn"}}],
                    "verify": [{"expect_visible": {"selector": "#result"}}],
                },
                {
                    "id": "step2",
                    "narration": "Check results",
                    "demo": False,
                },
            ],
        }
        path = tmp_path / "scenario.yml"
        path.write_text(yaml.dump(data), encoding="utf-8")

        scenario = load_scenario(path)
        assert scenario.app.name == "TestApp"
        assert scenario.app.base_url == "http://localhost:3000"
        assert scenario.app.viewport == {"width": 1280, "height": 720}
        assert scenario.app.ready_selector == "#app"
        assert scenario.app.ready_wait_ms == 5000
        assert len(scenario.steps) == 2
        assert scenario.steps[0].id == "step1"
        assert scenario.steps[0].narration == "Click the button"
        assert scenario.steps[0].act == [{"click": {"selector": "#btn"}}]
        assert scenario.steps[1].demo is False

    def test_missing_file_raises(self, tmp_path: Path):
        import pytest
        with pytest.raises(FileNotFoundError):
            load_scenario(tmp_path / "nonexistent.yml")

    def test_defaults_for_missing_fields(self, tmp_path: Path):
        data = {"steps": [{"id": "s1"}]}
        path = tmp_path / "scenario.yml"
        path.write_text(yaml.dump(data), encoding="utf-8")

        scenario = load_scenario(path)
        assert scenario.app.name == ""
        assert scenario.app.viewport == {"width": 1920, "height": 1080}
        assert scenario.app.ready_wait_ms == 3000
        assert scenario.steps[0].browser is True
        assert scenario.steps[0].demo is True
        assert scenario.steps[0].fallback_duration_ms == 5000
        assert scenario.steps[0].visual_type == "playwright"

    def test_empty_yaml(self, tmp_path: Path):
        path = tmp_path / "scenario.yml"
        path.write_text("{}", encoding="utf-8")
        scenario = load_scenario(path)
        assert scenario.steps == []
        assert scenario.app.name == ""

    def test_source_path_stored(self, tmp_path: Path):
        path = tmp_path / "scenario.yml"
        path.write_text(yaml.dump({"steps": []}), encoding="utf-8")
        scenario = load_scenario(path)
        assert scenario.source_path == path


# ── Scenario properties ──────────────────────────────────────────────


class TestScenarioProperties:
    def test_demo_steps(self):
        scenario = Scenario(steps=[
            ScenarioStep(id="a", demo=True),
            ScenarioStep(id="b", demo=False),
            ScenarioStep(id="c", demo=True),
        ])
        assert [s.id for s in scenario.demo_steps] == ["a", "c"]

    def test_browser_steps(self):
        scenario = Scenario(steps=[
            ScenarioStep(id="a", browser=True, demo=True),
            ScenarioStep(id="b", browser=False, demo=True),
            ScenarioStep(id="c", browser=True, demo=False),
        ])
        assert [s.id for s in scenario.browser_steps] == ["a"]

    def test_get_step(self):
        scenario = Scenario(steps=[
            ScenarioStep(id="alpha"),
            ScenarioStep(id="beta"),
        ])
        assert scenario.get_step("beta") is not None
        assert scenario.get_step("beta").id == "beta"
        assert scenario.get_step("gamma") is None

    def test_outline(self):
        scenario = Scenario(
            app=AppConfig(name="Demo", base_url="http://localhost:3000"),
            steps=[
                ScenarioStep(id="intro", narration="Welcome to the demo", demo=True),
                ScenarioStep(id="hidden", narration="Not shown", demo=False),
            ],
        )
        outline = scenario.outline()
        assert "Demo" in outline
        assert "localhost:3000" in outline
        assert "[demo]" in outline
        assert "[skip]" in outline
        assert "intro" in outline


# ── save_scenario ────────────────────────────────────────────────────


class TestSaveScenario:
    def test_roundtrip(self, tmp_path: Path):
        original = Scenario(
            app=AppConfig(name="MyApp", base_url="http://localhost:8080"),
            steps=[
                ScenarioStep(
                    id="draw",
                    narration="Draw a rectangle",
                    act=[{"click": {"selector": "#draw"}}],
                    verify=[{"expect_visible": {"selector": "#canvas"}}],
                ),
                ScenarioStep(id="review", narration="Review results", demo=False),
            ],
        )

        path = tmp_path / "out.yml"
        save_scenario(original, path)

        loaded = load_scenario(path)
        assert loaded.app.name == "MyApp"
        assert loaded.app.base_url == "http://localhost:8080"
        assert len(loaded.steps) == 2
        assert loaded.steps[0].id == "draw"
        assert loaded.steps[0].narration == "Draw a rectangle"
        assert loaded.steps[0].act == [{"click": {"selector": "#draw"}}]
        assert loaded.steps[1].demo is False

    def test_save_to_source_path(self, tmp_path: Path):
        path = tmp_path / "scenario.yml"
        scenario = Scenario(
            app=AppConfig(name="Test"),
            steps=[ScenarioStep(id="s1")],
            source_path=path,
        )
        result = save_scenario(scenario)
        assert result == path
        assert path.exists()

    def test_save_without_path_raises(self):
        import pytest
        scenario = Scenario()
        with pytest.raises(ValueError):
            save_scenario(scenario)

    def test_save_omits_defaults(self, tmp_path: Path):
        """Default values should not be written to YAML to keep it clean."""
        scenario = Scenario(
            app=AppConfig(name="Clean"),
            steps=[ScenarioStep(id="s1", narration="Hello")],
        )
        path = tmp_path / "clean.yml"
        save_scenario(scenario, path)
        raw = yaml.safe_load(path.read_text())
        step = raw["steps"][0]
        assert "browser" not in step
        assert "demo" not in step
        assert "fallback_duration_ms" not in step
        assert "visual_type" not in step

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "scenario.yml"
        scenario = Scenario(app=AppConfig(name="Nested"), steps=[])
        save_scenario(scenario, path)
        assert path.exists()
