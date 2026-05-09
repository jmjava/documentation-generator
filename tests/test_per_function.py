"""Tests for ``docgen.per_function`` — Playwright spec → per-function manifest.

Exercises the discovery path with a synthetic external-project layout (no
dogfood-specific names) and the orchestrator with a mocked OpenAI client so we
never make a real network call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from docgen.config import Config
from docgen.per_function import (
    GeneratedManifest,
    SpecBinding,
    build_manifest,
    discover_playwright_specs,
    generate_narration_plan,
    per_function_output_dir,
    write_per_function_manifests,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic external project (no dogfood names)
# ---------------------------------------------------------------------------


def _write_external_project(repo_root: Path) -> Path:
    """Create a fictional external Playwright project under ``repo_root/app``.

    Uses generic names (``app``, ``home.spec.ts``, ``[data-testid='greeting']``)
    so the test asserts the discovery code is project-agnostic — no ``vite``,
    ``dogfood``, or ``lesson-compile`` literals.
    """
    proj = repo_root / "app"
    proj.mkdir(parents=True)
    (proj / "package.json").write_text(
        json.dumps(
            {
                "name": "external-app",
                "private": True,
                "devDependencies": {"@playwright/test": "^1.49.0"},
            }
        ),
        encoding="utf-8",
    )
    (proj / "playwright.config.ts").write_text(
        'import { defineConfig } from "@playwright/test";\n'
        "export default defineConfig({\n"
        '  testDir: ".",\n'
        '  use: { baseURL: "http://127.0.0.1:4321" },\n'
        "  webServer: {\n"
        '    command: "npm run dev",\n'
        '    url: "http://127.0.0.1:4321",\n'
        "  },\n"
        "});\n",
        encoding="utf-8",
    )
    (proj / "home.spec.ts").write_text(
        'import { expect, test } from "@playwright/test";\n'
        "\n"
        'test("home page shows greeting", async ({ page }) => {\n'
        '  await page.goto("/");\n'
        '  await expect(page.getByTestId("greeting")).toContainText("hello");\n'
        "});\n",
        encoding="utf-8",
    )
    return proj


def _write_demo_bundle(repo_root: Path) -> Path:
    """Minimum viable docgen bundle with a docgen.yaml so we can build a Config."""
    bundle = repo_root / "docs" / "demos"
    (bundle / "narration").mkdir(parents=True)
    (bundle / "audio").mkdir(parents=True)
    (bundle / "animations").mkdir(parents=True)
    (bundle / "terminal").mkdir(parents=True)
    (bundle / "recordings").mkdir(parents=True)
    cfg_text = (
        "repo_root: ../..\n"
        "dirs:\n"
        "  narration: narration\n"
        "  audio: audio\n"
        "  animations: animations\n"
        "  terminal: terminal\n"
        "  recordings: recordings\n"
        "segments:\n"
        "  default: ['01']\n"
        "  all: ['01']\n"
        "segment_names:\n"
        "  '01': 01-intro\n"
    )
    (bundle / "docgen.yaml").write_text(cfg_text, encoding="utf-8")
    return bundle


def _build_config(bundle: Path) -> Config:
    yaml_path = bundle / "docgen.yaml"
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return Config(yaml_path=yaml_path, base_dir=bundle, raw=raw)


# ---------------------------------------------------------------------------
# Mocked OpenAI client
# ---------------------------------------------------------------------------


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubResponse:
    choices: list[_StubChoice]


class _StubChatCompletions:
    def __init__(self, payloads: list[dict[str, Any]]):
        self._payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _StubResponse:
        self.calls.append(kwargs)
        if not self._payloads:
            raise AssertionError("stub OpenAI client received unexpected extra call")
        payload = self._payloads.pop(0)
        return _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(payload)))]
        )


class _StubChat:
    def __init__(self, completions: _StubChatCompletions):
        self.completions = completions


class StubOpenAIClient:
    def __init__(self, payloads: list[dict[str, Any]]):
        self.completions = _StubChatCompletions(payloads)
        self.chat = _StubChat(self.completions)


def _good_payload() -> dict[str, Any]:
    return {
        "intent": "A visitor opens the home page and sees the greeting heading appear.",
        "narration_steps": [
            {
                "api_name": "page.goto",
                "say": "The browser navigates to the application home page.",
            },
            {
                "api_name": "expect.toContainText",
                "say": "A greeting heading is visible at the top of the page.",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Tests — discovery
# ---------------------------------------------------------------------------


def test_spec_binding_slug_is_filename_safe() -> None:
    proj = Path("/tmp/proj")
    spec = proj / "home.spec.ts"
    binding = SpecBinding(
        project_dir=proj,
        spec_path=spec,
        test_title="Home page shows: greeting!",
    )
    assert binding.slug == "home-home-page-shows-greeting"
    assert "/" not in binding.slug
    assert binding.slug.lower() == binding.slug


def test_spec_binding_identifier_uses_project_relative_path() -> None:
    proj = Path("/tmp/proj")
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "tests" / "home.spec.ts",
        test_title="home shows greeting",
    )
    assert binding.identifier == "proj/tests/home.spec.ts::home shows greeting"


def test_discover_playwright_specs_skips_when_no_npm_install(tmp_path: Path) -> None:
    """No node_modules → npx playwright test --list fails → discovery returns []."""
    _write_external_project(tmp_path)
    assert discover_playwright_specs(tmp_path) == []


# ---------------------------------------------------------------------------
# Tests — narration plan generation (LLM stub)
# ---------------------------------------------------------------------------


def test_generate_narration_plan_returns_clean_pair(tmp_path: Path) -> None:
    proj = _write_external_project(tmp_path)
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="home page shows greeting",
    )
    stub = StubOpenAIClient([_good_payload()])

    intent, steps = generate_narration_plan(binding, openai_client=stub)

    assert intent.startswith("A visitor")
    assert len(steps) == 2
    assert steps[0]["api_name"] == "page.goto"
    assert steps[1]["api_name"] == "expect.toContainText"
    for s in steps:
        assert s["say"]
        assert "`" not in s["say"]


def test_generate_narration_plan_rejects_missing_intent(tmp_path: Path) -> None:
    proj = _write_external_project(tmp_path)
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="t",
    )
    bad = {"narration_steps": [{"api_name": "page.goto", "say": "ok"}]}
    stub = StubOpenAIClient([bad])
    with pytest.raises(RuntimeError, match="intent"):
        generate_narration_plan(binding, openai_client=stub)


def test_generate_narration_plan_rejects_empty_steps(tmp_path: Path) -> None:
    proj = _write_external_project(tmp_path)
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="t",
    )
    bad = {"intent": "ok intent line", "narration_steps": []}
    stub = StubOpenAIClient([bad])
    with pytest.raises(RuntimeError, match="narration_steps"):
        generate_narration_plan(binding, openai_client=stub)


def test_generate_narration_plan_rejects_non_user_api(tmp_path: Path) -> None:
    """``browserContext.newPage`` is internal — not a user-visible step."""
    proj = _write_external_project(tmp_path)
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="t",
    )
    bad = {
        "intent": "ok intent line",
        "narration_steps": [
            {"api_name": "browserContext.newPage", "say": "internal call"},
        ],
    }
    stub = StubOpenAIClient([bad])
    with pytest.raises(RuntimeError, match="user-visible"):
        generate_narration_plan(binding, openai_client=stub)


def test_generate_narration_plan_rejects_backticks(tmp_path: Path) -> None:
    proj = _write_external_project(tmp_path)
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="t",
    )
    bad = {
        "intent": "ok intent line",
        "narration_steps": [
            {"api_name": "page.goto", "say": "Open the `home` page."},
        ],
    }
    stub = StubOpenAIClient([bad])
    with pytest.raises(RuntimeError, match="backticks"):
        generate_narration_plan(binding, openai_client=stub)


# ---------------------------------------------------------------------------
# Tests — manifest assembly
# ---------------------------------------------------------------------------


def test_build_manifest_shape_is_demo_function_consumable() -> None:
    proj = Path("/tmp/proj")
    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="home page shows greeting",
    )
    steps = [
        {"api_name": "page.goto", "say": "navigate to the home page"},
        {"api_name": "expect.toBeVisible", "say": "see the greeting"},
    ]
    m = build_manifest(binding, intent="A visitor sees a greeting.", narration_steps=steps)

    assert m["identifier"] == "proj/home.spec.ts::home page shows greeting"
    assert m["intent"] == "A visitor sees a greeting."
    demo = m["demonstration"]
    assert demo["kind"] == "playwright"
    assert demo["spec"] == str(proj / "home.spec.ts")
    assert demo["grep"] == "home page shows greeting"
    assert demo["cwd"] == str(proj)
    assert "url" not in demo
    assert "actions" not in demo
    assert m["narration_steps"] == steps


# ---------------------------------------------------------------------------
# Tests — orchestrator with mocked OpenAI
# ---------------------------------------------------------------------------


def test_write_per_function_manifests_writes_yaml(tmp_path: Path) -> None:
    proj = _write_external_project(tmp_path)
    bundle = _write_demo_bundle(tmp_path)
    cfg = _build_config(bundle)

    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="home page shows greeting",
    )
    stub = StubOpenAIClient([_good_payload()])
    results = write_per_function_manifests(
        cfg, bindings=[binding], openai_client=stub, force=True
    )

    assert len(results) == 1
    out = results[0]
    assert isinstance(out, GeneratedManifest)
    assert out.manifest_path.is_file()
    assert out.manifest_path.parent == per_function_output_dir(cfg)
    assert not (out.manifest_path.parent / f"{out.slug}.html").exists()

    written = yaml.safe_load(out.manifest_path.read_text(encoding="utf-8"))
    assert written["demonstration"]["kind"] == "playwright"
    assert written["demonstration"]["spec"].endswith("home.spec.ts")
    assert written["demonstration"]["grep"] == "home page shows greeting"
    assert len(written["narration_steps"]) == 2


def test_write_per_function_manifests_skips_existing_without_force(tmp_path: Path) -> None:
    proj = _write_external_project(tmp_path)
    bundle = _write_demo_bundle(tmp_path)
    cfg = _build_config(bundle)

    binding = SpecBinding(
        project_dir=proj,
        spec_path=proj / "home.spec.ts",
        test_title="home page shows greeting",
    )
    out_dir = per_function_output_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{binding.slug}.docgen.yaml").write_text(
        "identifier: pre-existing\n", encoding="utf-8"
    )

    stub = StubOpenAIClient([])  # no payloads — proves we never call out
    results = write_per_function_manifests(
        cfg, bindings=[binding], openai_client=stub, force=False
    )
    assert results == []
    assert stub.completions.calls == []
