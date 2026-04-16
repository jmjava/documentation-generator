"""YAML scenario loader for Playwright-based recording workflows.

A scenario file defines browser automation steps declaratively in YAML,
eliminating the need for Python capture scripts. Each step can have
narration, browser actions, and verification assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AppConfig:
    """Application-level configuration from scenario YAML."""

    name: str = ""
    base_url: str = ""
    start_params: dict[str, Any] = field(default_factory=dict)
    viewport: dict[str, int] = field(default_factory=lambda: {"width": 1920, "height": 1080})
    ready_selector: str = ""
    ready_wait_ms: int = 3000


@dataclass
class ScenarioStep:
    """A single step in a demo scenario."""

    id: str
    narration: str = ""
    browser: bool = True
    demo: bool = True
    fallback_duration_ms: int = 5000
    visual_type: str = "playwright"
    act: list[dict[str, Any]] = field(default_factory=list)
    verify: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Scenario:
    """Complete scenario loaded from YAML."""

    app: AppConfig = field(default_factory=AppConfig)
    steps: list[ScenarioStep] = field(default_factory=list)
    source_path: Path | None = None

    @property
    def demo_steps(self) -> list[ScenarioStep]:
        """Return only steps marked for demo recording."""
        return [s for s in self.steps if s.demo]

    @property
    def browser_steps(self) -> list[ScenarioStep]:
        """Return only steps that involve browser interaction."""
        return [s for s in self.steps if s.browser and s.demo]

    def get_step(self, step_id: str) -> ScenarioStep | None:
        """Find a step by ID."""
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def outline(self) -> str:
        """Return a human-readable outline of the scenario."""
        lines = [f"Scenario: {self.app.name}"]
        lines.append(f"  URL: {self.app.base_url}")
        lines.append(f"  Viewport: {self.app.viewport.get('width', '?')}x{self.app.viewport.get('height', '?')}")
        lines.append(f"  Steps: {len(self.steps)} ({len(self.demo_steps)} demo)")
        lines.append("")
        for i, step in enumerate(self.steps, 1):
            demo_flag = "[demo]" if step.demo else "[skip]"
            vtype = step.visual_type
            narr_preview = step.narration[:60] + "..." if len(step.narration) > 60 else step.narration
            lines.append(f"  {i}. {demo_flag} [{vtype}] {step.id}: {narr_preview}")
            if step.act:
                lines.append(f"     Actions: {len(step.act)}")
            if step.verify:
                lines.append(f"     Verify: {len(step.verify)}")
        return "\n".join(lines)


def load_scenario(path: str | Path) -> Scenario:
    """Load a scenario from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    app_raw = raw.get("app", {})
    app = AppConfig(
        name=str(app_raw.get("name", "")),
        base_url=str(app_raw.get("base_url", "")),
        start_params=app_raw.get("start_params", {}),
        viewport=app_raw.get("viewport", {"width": 1920, "height": 1080}),
        ready_selector=str(app_raw.get("ready_selector", "")),
        ready_wait_ms=int(app_raw.get("ready_wait_ms", 3000)),
    )

    steps: list[ScenarioStep] = []
    for step_raw in raw.get("steps", []):
        steps.append(ScenarioStep(
            id=str(step_raw.get("id", "")),
            narration=str(step_raw.get("narration", "")),
            browser=bool(step_raw.get("browser", True)),
            demo=bool(step_raw.get("demo", True)),
            fallback_duration_ms=int(step_raw.get("fallback_duration_ms", 5000)),
            visual_type=str(step_raw.get("visual_type", "playwright")),
            act=step_raw.get("act", []),
            verify=step_raw.get("verify", []),
        ))

    return Scenario(app=app, steps=steps, source_path=path)


def save_scenario(scenario: Scenario, path: str | Path | None = None) -> Path:
    """Save a scenario back to YAML."""
    path = Path(path) if path else scenario.source_path
    if path is None:
        raise ValueError("No output path specified and scenario has no source_path")

    raw: dict[str, Any] = {
        "app": {
            "name": scenario.app.name,
            "base_url": scenario.app.base_url,
            "viewport": scenario.app.viewport,
        },
    }
    if scenario.app.start_params:
        raw["app"]["start_params"] = scenario.app.start_params
    if scenario.app.ready_selector:
        raw["app"]["ready_selector"] = scenario.app.ready_selector
    if scenario.app.ready_wait_ms != 3000:
        raw["app"]["ready_wait_ms"] = scenario.app.ready_wait_ms

    raw["steps"] = []
    for step in scenario.steps:
        step_raw: dict[str, Any] = {"id": step.id}
        if step.narration:
            step_raw["narration"] = step.narration
        if not step.browser:
            step_raw["browser"] = False
        if not step.demo:
            step_raw["demo"] = False
        if step.fallback_duration_ms != 5000:
            step_raw["fallback_duration_ms"] = step.fallback_duration_ms
        if step.visual_type != "playwright":
            step_raw["visual_type"] = step.visual_type
        if step.act:
            step_raw["act"] = step.act
        if step.verify:
            step_raw["verify"] = step.verify
        raw["steps"].append(step_raw)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, sort_keys=False)

    return path
