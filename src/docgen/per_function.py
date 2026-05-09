"""Generate per-function ``.docgen.yaml`` manifests from raw Playwright specs.

Pipeline:

1. **Discover** Playwright projects under the repo (``detect_playwright_project_dirs``)
   and their tests (``discover_node_playwright_tests``).
2. For each ``(spec, test_title)`` pair, ask OpenAI for a JSON object with two
   fields derived from the spec source:

   * ``intent`` — one short sentence describing what a viewer sees the test
     accomplish (used for fragment metadata + as a fallback narration).
   * ``narration_steps`` — an ordered list of ``{api_name, say}`` entries, one
     per user-visible Playwright API call the test executes
     (``page.goto``, ``locator.click``, ``locator.fill``, ``expect(...)``,
     etc.). The ordering must match the call order in the spec.

3. **Write** ``<base_dir>/per-function/<slug>.docgen.yaml`` with
   ``demonstration.kind: playwright`` + ``spec`` + ``grep`` + ``cwd``, and
   ``narration_steps`` embedded so ``docgen demo-function`` can later sync
   each ``say`` to the matching trace event without a second LLM call.

Rendering is the existing ``docgen demo-function`` spec-mode path: it shells
out to ``npx playwright test --trace=on --video=on``, which reads the
project's own ``playwright.config.*`` ``webServer:`` block to start the dev
server, runs the spec headlessly in Chromium against the real app, records
the ``.webm`` and a ``trace.zip``, and tears the server down. ``demo-function``
then parses ``trace.zip`` (see :mod:`docgen.pf_trace`), zips real recording
timestamps onto ``narration_steps``, and synthesises one TTS clip per step at
its actual moment in the video.

This module contains **no** project-specific names, paths, or selectors —
the same flow works for any project with ``package.json`` +
``@playwright/test`` + ``playwright.config.*`` (with a ``webServer:`` block) +
``npm install`` run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from docgen.init import detect_playwright_project_dirs
from docgen.test_discovery import (
    discover_node_playwright_tests,
    find_playwright_config,
    parse_playwright_config_insights,
)

if TYPE_CHECKING:
    from docgen.config import Config


_DEFAULT_LLM_MODEL = "gpt-4o-mini"
_DEFAULT_LLM_TEMPERATURE = 0.3
_DEFAULT_DURATION_SECONDS = 30
_DEFAULT_RESOLUTION = "1280x720"
_DEFAULT_PLAYBACK_SPEED_FACTOR = 0.7
_DEFAULT_SPEC_BUDGET_BYTES = 12_000

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Same prefix set the trace parser keeps — surfacing it here lets us tell the
# LLM exactly which API names it should enumerate.
_TRACE_VISIBLE_API_PREFIXES: tuple[str, ...] = (
    "page.",
    "locator.",
    "expect.",
    "frame.",
    "frameLocator.",
    "keyboard.",
    "mouse.",
    "elementHandle.",
)

_SYSTEM_PROMPT = """You read one Playwright `.spec` test and produce TWO outputs that drive a narrated video of the test running against the real app:

1) ``intent``: ONE sentence, present-tense, plain spoken English (8-22 words). Describe what a viewer SEES on screen — the user-facing behaviour the test demonstrates. No backticks, no markdown, no quoted code, no file names, no test framework jargon (do not say "playwright", "spec", "assertion", "selector", "test", "expect"). Do not start with "This test ...".

2) ``narration_steps``: an ORDERED array, one entry per user-visible Playwright API call the test executes, in execution order. Each entry has:
   - ``api_name``: the Playwright API name as it would appear in a trace, e.g. "page.goto", "locator.click", "locator.fill", "page.waitForLoadState", "expect.toBeVisible", "expect.toHaveText", "expect.toContainText". Use the dotted ``class.method`` form. Allowed prefixes: page., locator., expect., frame., frameLocator., keyboard., mouse., elementHandle..
   - ``say``: a SHORT spoken phrase, 4 to 9 words, present-tense, narrating what is visible on screen at that step. Each phrase is a TTS clip that must play synchronously with the matching action — keep them tight so they fit between traced API calls. No markdown, no backticks, no jargon, no full sentences with subordinate clauses. Examples: "Open the home page.", "The heading appears.", "Type the lesson topic.", "Click the compile button.", "The output appears."

Rules for the steps list:
- Include EVERY user-visible call the test makes — navigations, clicks, types, presses, waits-for-load-state, and every ``expect(...)`` chain.
- Do NOT include framework setup or fixture lifecycle (no ``test``, ``test.beforeEach``, ``browserContext``, ``tracing``, ``page._*``).
- Order MUST match execution order in the spec source.
- The first step MUST correspond to the first navigation or interaction (typically ``page.goto``).
- Every step MUST have a non-empty ``say`` — there is no silent step.

Return EXACTLY one JSON object with keys ``intent`` and ``narration_steps``. No markdown fences, no commentary."""


@dataclass
class SpecBinding:
    """One discovered ``(project, spec, test)`` tuple."""

    project_dir: Path
    spec_path: Path
    test_title: str
    base_url: str | None = None
    web_server_url: str | None = None
    web_server_command: str | None = None

    @property
    def slug(self) -> str:
        """``<spec_stem>__<test_title>`` lowercased + filename-safe."""
        spec_stem = self.spec_path.stem
        if spec_stem.endswith(".spec"):
            spec_stem = spec_stem[: -len(".spec")]
        title_part = self.test_title.strip().lower()
        combined = f"{spec_stem}__{title_part}"
        return _SLUG_RE.sub("-", combined).strip("-") or "test"

    @property
    def identifier(self) -> str:
        """``<project_dir_name>/<spec_relpath>::<test_title>``."""
        try:
            rel = self.spec_path.relative_to(self.project_dir)
            spec_part = str(rel).replace("\\", "/")
        except ValueError:
            spec_part = self.spec_path.name
        return f"{self.project_dir.name}/{spec_part}::{self.test_title}"


@dataclass
class GeneratedManifest:
    """Output of one per-function generation."""

    slug: str
    manifest_path: Path
    binding: SpecBinding
    manifest: dict[str, Any] = field(default_factory=dict)


# Backwards-compatible alias retained briefly for any in-flight imports/tests.
GeneratedPair = GeneratedManifest


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_playwright_specs(repo_root: Path) -> list[SpecBinding]:
    """Find every ``(project, spec, test)`` tuple under ``repo_root``.

    Iterates :func:`detect_playwright_project_dirs` and runs
    :func:`discover_node_playwright_tests` per project. Returns an empty list when
    no Playwright project is detected, when ``node_modules`` are missing, or when
    ``npx playwright test --list`` fails.
    """
    repo_root = repo_root.resolve()
    bindings: list[SpecBinding] = []
    seen: set[tuple[str, str]] = set()
    for proj in detect_playwright_project_dirs(repo_root):
        tests = discover_node_playwright_tests(proj)
        cfg_path = find_playwright_config(proj)
        cfg_insights = parse_playwright_config_insights(cfg_path) if cfg_path else {}
        base_url = cfg_insights.get("base_url")
        web_server_url = cfg_insights.get("web_server_url")
        web_server_command = cfg_insights.get("web_server_command")
        for t in tests:
            spec_abs = (proj / t.spec_path).resolve()
            if not spec_abs.is_file():
                continue
            try:
                key_spec = str(spec_abs.relative_to(repo_root))
            except ValueError:
                key_spec = str(spec_abs)
            key = (key_spec, t.title)
            if key in seen:
                continue
            seen.add(key)
            bindings.append(
                SpecBinding(
                    project_dir=proj,
                    spec_path=spec_abs,
                    test_title=t.title,
                    base_url=base_url,
                    web_server_url=web_server_url,
                    web_server_command=web_server_command,
                )
            )
    return bindings


# ---------------------------------------------------------------------------
# OpenAI generation — intent + narration_steps in a single call
# ---------------------------------------------------------------------------


def _read_spec_excerpt(spec_path: Path, *, budget_bytes: int) -> str:
    text = spec_path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= budget_bytes:
        return text
    return text[:budget_bytes] + "\n… [truncated]\n"


def _build_user_prompt(binding: SpecBinding, *, spec_excerpt: str) -> str:
    return (
        f"Test title: {binding.test_title}\n"
        "\n"
        "--- SPEC SOURCE ---\n"
        f"FILE: {binding.spec_path.name}\n"
        "```\n"
        f"{spec_excerpt}\n"
        "```\n"
        "--- END SPEC SOURCE ---\n"
        "\n"
        "Return one JSON object with keys 'intent' (string) and "
        "'narration_steps' (array of {api_name, say} objects, in execution order)."
    )


def generate_narration_plan(
    binding: SpecBinding,
    *,
    model: str = _DEFAULT_LLM_MODEL,
    temperature: float = _DEFAULT_LLM_TEMPERATURE,
    spec_budget_bytes: int = _DEFAULT_SPEC_BUDGET_BYTES,
    openai_client: Any | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Return ``(intent, narration_steps)`` for one ``(spec, test)``.

    Raises :class:`RuntimeError` on transport / parsing failures. Output is
    structurally validated:

    * ``intent`` is a non-empty single-line string with no backticks.
    * ``narration_steps`` is a non-empty list of ``{api_name, say}`` dicts.
    * Every ``api_name`` matches one of :data:`_TRACE_VISIBLE_API_PREFIXES`.
    * Every ``say`` is a non-empty string with no backticks.
    """
    spec_excerpt = _read_spec_excerpt(
        binding.spec_path, budget_bytes=spec_budget_bytes
    )
    user_prompt = _build_user_prompt(binding, spec_excerpt=spec_excerpt)

    if openai_client is None:
        import openai

        openai_client = openai.OpenAI()

    response = openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=float(temperature),
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"per-function-generate: model returned non-JSON for {binding.slug}: {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"per-function-generate: top-level JSON must be an object for {binding.slug}, "
            f"got {type(parsed).__name__}"
        )
    intent = parsed.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        raise RuntimeError(
            f"per-function-generate: 'intent' missing or empty for {binding.slug}"
        )
    intent_clean = " ".join(intent.split())
    if "`" in intent_clean:
        raise RuntimeError(
            f"per-function-generate: 'intent' for {binding.slug} contains backticks"
        )

    steps_raw = parsed.get("narration_steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise RuntimeError(
            f"per-function-generate: 'narration_steps' must be a non-empty list "
            f"for {binding.slug}"
        )
    steps: list[dict[str, str]] = []
    for i, step in enumerate(steps_raw):
        if not isinstance(step, dict):
            raise RuntimeError(
                f"per-function-generate: narration_steps[{i}] must be a mapping "
                f"for {binding.slug}, got {type(step).__name__}"
            )
        api_name = step.get("api_name")
        say = step.get("say")
        if not isinstance(api_name, str) or not api_name.strip():
            raise RuntimeError(
                f"per-function-generate: narration_steps[{i}].api_name missing for "
                f"{binding.slug}"
            )
        api_clean = api_name.strip()
        if not any(
            api_clean.startswith(prefix) for prefix in _TRACE_VISIBLE_API_PREFIXES
        ):
            raise RuntimeError(
                f"per-function-generate: narration_steps[{i}].api_name "
                f"{api_clean!r} for {binding.slug} is not a user-visible "
                f"Playwright API (allowed prefixes: {_TRACE_VISIBLE_API_PREFIXES})."
            )
        if not isinstance(say, str) or not say.strip():
            raise RuntimeError(
                f"per-function-generate: narration_steps[{i}].say missing for "
                f"{binding.slug}"
            )
        say_clean = " ".join(say.split())
        if "`" in say_clean:
            raise RuntimeError(
                f"per-function-generate: narration_steps[{i}].say for "
                f"{binding.slug} contains backticks"
            )
        steps.append({"api_name": api_clean, "say": say_clean})
    return intent_clean, steps


# ---------------------------------------------------------------------------
# Manifest assembly + writing
# ---------------------------------------------------------------------------


def build_manifest(
    binding: SpecBinding,
    *,
    intent: str,
    narration_steps: list[dict[str, str]],
) -> dict[str, Any]:
    """Assemble the deterministic manifest dict for one ``(spec, test)``.

    Consumed by ``docgen demo-function`` in spec-record mode:

    * ``demonstration.kind: playwright`` + ``spec`` + ``grep`` + ``cwd``
      triggers the ``npx playwright test --trace=on --video=on`` path; the
      project's own ``playwright.config.*`` ``webServer:`` block starts and
      stops the dev server.
    * ``narration_steps`` is preserved in the manifest so the renderer can
      align each ``say`` with the matching trace event (no second LLM call).
    """
    return {
        "identifier": binding.identifier,
        "intent": intent,
        "demonstration": {
            "kind": "playwright",
            "spec": str(binding.spec_path),
            "grep": binding.test_title,
            "cwd": str(binding.project_dir),
        },
        "narration_steps": [
            {"api_name": s["api_name"], "say": s["say"]} for s in narration_steps
        ],
        "output_budget": {
            "duration_seconds": _DEFAULT_DURATION_SECONDS,
            "resolution": _DEFAULT_RESOLUTION,
            "playback_speed_factor": _DEFAULT_PLAYBACK_SPEED_FACTOR,
        },
        "assertions_to_surface": [],
    }


def per_function_output_dir(cfg: "Config") -> Path:
    return cfg.base_dir / "per-function"


def write_per_function_manifests(
    cfg: "Config",
    *,
    bindings: list[SpecBinding] | None = None,
    model: str | None = None,
    temperature: float | None = None,
    force: bool = False,
    openai_client: Any | None = None,
) -> list[GeneratedManifest]:
    """Generate ``<slug>.docgen.yaml`` for every discovered spec/test.

    When ``force`` is False, any existing manifest with the same path is
    skipped. The output directory is created when missing.
    """
    if bindings is None:
        bindings = discover_playwright_specs(cfg.repo_root)
    out_dir = per_function_output_dir(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    settings = cfg.raw.get("per_function_generate") or {}
    use_model = model or settings.get("model") or _DEFAULT_LLM_MODEL
    use_temp = (
        temperature
        if temperature is not None
        else float(settings.get("temperature", _DEFAULT_LLM_TEMPERATURE))
    )
    spec_budget = int(
        settings.get("max_spec_bytes", _DEFAULT_SPEC_BUDGET_BYTES)
    )

    results: list[GeneratedManifest] = []
    for binding in bindings:
        manifest_path = out_dir / f"{binding.slug}.docgen.yaml"
        if not force and manifest_path.is_file():
            continue
        intent, narration_steps = generate_narration_plan(
            binding,
            model=use_model,
            temperature=use_temp,
            spec_budget_bytes=spec_budget,
            openai_client=openai_client,
        )
        manifest = build_manifest(
            binding, intent=intent, narration_steps=narration_steps
        )
        with manifest_path.open("w", encoding="utf-8") as fp:
            yaml.safe_dump(manifest, fp, sort_keys=False, allow_unicode=True)
        results.append(
            GeneratedManifest(
                slug=binding.slug,
                manifest_path=manifest_path,
                binding=binding,
                manifest=manifest,
            )
        )
    return results


write_per_function_pairs = write_per_function_manifests
