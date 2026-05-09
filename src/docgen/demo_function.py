"""Per-function video docs subcommand: declarative Playwright + narration.

This module implements `docgen demo-function`, which renders one short MP4 per
function from a declarative manifest (either a `*.docgen.yaml` sidecar or a
`@pytest.mark.docgen(...)` decorator on a Python test). Playwright **can**
instead run an annotated `@playwright/test` spec plus `--grep`, or `kind: cli`
can point at a VHS `.tape` file. The output is one function → one ≤60s clip
with a one-sentence narration, a poster frame, on-screen assertion captions, a
stable URL fragment, and a JSON manifest snapshot.

Exit codes (used by `docgen.cli:demo_function`):
    0   render succeeded; all five artifacts written
    1   manifest invalid OR render failed
    2   required tooling missing (ffmpeg / playwright / browser)
    78  manifest is a placeholder (kind=playwright with no url) — neutral skip

Supported action `kind`s: goto, click, fill, type, wait_for, wait_for_text,
wait, screenshot. Unknown kinds raise `ManifestError`.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from docgen.config import Config
from docgen.openai_retry import call_with_rate_limit_retries

# Exit code for "neutral skip" on placeholder manifests. Mirrors Tekton's
# documented Skip exit code so CI pipelines do not treat placeholder-shaped
# manifests as failures.
EXIT_NEUTRAL_SKIP = 78
EXIT_TOOLING_MISSING = 2
EXIT_INVALID = 1
EXIT_OK = 0

HARD_CAP_SECONDS = 60
DEFAULT_DURATION_SECONDS = 30
DEFAULT_RESOLUTION = "1280x720"
RESOLUTION_RE = re.compile(r"^\d+x\d+$")
FRAGMENT_PREFIX_RE = re.compile(r"^fn-[a-z0-9-]+$")

# `output_budget.playback_speed_factor`: post-capture retiming via ffmpeg setpts.
# <1.0 slows the visual (longer duration), >1.0 speeds it up. Audio is NOT stretched —
# narration plays at natural pace and is padded with trailing silence to match the
# retimed video length, so a slowed Playwright capture stays legible while the
# one-line TTS summary still lands without distortion.
DEFAULT_PLAYBACK_SPEED_FACTOR = 1.0
MIN_PLAYBACK_SPEED_FACTOR = 0.25
MAX_PLAYBACK_SPEED_FACTOR = 4.0

SUPPORTED_ACTION_KINDS = (
    "goto",
    "click",
    "fill",
    "type",
    "wait_for",
    "wait_for_text",
    "wait",
    "screenshot",
)

CACHED_ARTIFACTS = ("rendered.mp4", "poster.png", "fragment.txt", "manifest.json")

_PLAYWRIGHT_SPEC_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts"})


class ManifestError(ValueError):
    """Raised when a manifest is malformed or violates the documented schema."""


class PlaceholderManifest(Exception):
    """Raised for placeholder manifests (kind=playwright with no url).

    The CLI translates this into exit code 78 (neutral skip).
    """


class ToolingMissingError(RuntimeError):
    """Raised when a required external tool (ffmpeg, playwright) is missing.

    The CLI translates this into exit code 2 and prints the install hint that
    accompanies the exception.
    """

    def __init__(self, message: str, install_hint: str) -> None:
        super().__init__(message)
        self.install_hint = install_hint


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Action:
    """One declarative browser action.

    `kind` is one of `SUPPORTED_ACTION_KINDS`. `params` carries the rest of
    the YAML mapping for the action (selector, value, ms, etc.). `say`
    (optional) is the narration sentence spoken aloud at the moment this
    action runs — when any action has ``say``, the renderer composes one
    TTS clip per action, places each at its captured timestamp, and burns
    a caption at the matching moment instead of evenly spreading
    ``assertions_to_surface`` across the clip.
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    say: str | None = None

    @classmethod
    def from_mapping(cls, raw: Any) -> "Action":
        if not isinstance(raw, dict):
            raise ManifestError(f"action must be a mapping, got: {type(raw).__name__}")
        kind = raw.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ManifestError("action missing required field: 'kind'")
        if kind not in SUPPORTED_ACTION_KINDS:
            supported = ", ".join(SUPPORTED_ACTION_KINDS)
            raise ManifestError(
                f"unsupported action kind: '{kind}' (supported: {supported})"
            )
        say_raw = raw.get("say")
        say: str | None = None
        if say_raw is not None:
            if not isinstance(say_raw, str):
                raise ManifestError(
                    f"action.say must be a string, got: {type(say_raw).__name__}"
                )
            say_stripped = say_raw.strip()
            if say_stripped:
                say = say_stripped
        params = {k: v for k, v in raw.items() if k not in {"kind", "say"}}
        return cls(kind=kind, params=params, say=say)


@dataclass
class Manifest:
    """Normalised, validated manifest for one demo-function render."""

    identifier: str
    intent: str
    kind: str
    url: str | None = None
    actions: list[Action] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    assertions_to_surface: list[str] = field(default_factory=list)
    duration_seconds: int = DEFAULT_DURATION_SECONDS
    resolution: str = DEFAULT_RESOLUTION
    playback_speed_factor: float = DEFAULT_PLAYBACK_SPEED_FACTOR
    source_path: Path | None = None
    # File whose bytes define the demo "function" for caching (spec, tape, or manifest).
    fn_source_path: Path | None = None
    # Playwright test recording (npx @playwright/test). When set, `actions` / `url` are unused.
    pw_spec: Path | None = None
    pw_grep: str | None = None
    pw_cwd: Path | None = None
    pw_base_url: str | None = None
    # Optional per-step narration plan for kind=playwright + spec mode. Each
    # entry is ``{"api_name": "page.click", "say": "..."}`` in spec execution
    # order; the renderer parses Playwright's ``trace.zip`` after the run and
    # zips real recording timestamps onto these ``say`` lines so the TTS
    # narration syncs to the actual moment each action fires on screen.
    pw_narration_steps: list[dict[str, str]] = field(default_factory=list)
    # CLI / VHS demo: path to a `.tape` file (relative paths resolve near manifest).
    cli_tape: Path | None = None

    @property
    def viewport(self) -> tuple[int, int]:
        w, h = self.resolution.split("x", 1)
        return int(w), int(h)

    @property
    def fragment_id(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.identifier.lower())
        slug = re.sub(r"-+", "-", slug).strip("-")
        return f"fn-{slug}" if slug else "fn-unknown"

    @property
    def cache_key(self) -> str:
        """sha256(fn_source_sha + intent_sha + fixture_sha), first 16 hex chars."""
        if self.fn_source_path and self.fn_source_path.exists():
            fn_src = hashlib.sha256(self.fn_source_path.read_bytes()).hexdigest()
        else:
            blob = "|".join(
                (
                    self.identifier,
                    self.kind,
                    self.url or "",
                    str(self.pw_spec or ""),
                    self.pw_grep or "",
                    str(self.cli_tape or ""),
                    json.dumps([a.__dict__ for a in self.actions], sort_keys=True),
                )
            )
            fn_src = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        intent_sha = hashlib.sha256(self.intent.encode("utf-8")).hexdigest()
        fix = hashlib.sha256()
        for fixture in sorted(self.fixtures):
            content = self._read_fixture_bytes(fixture)
            if content is not None:
                fix.update(content)
            fix.update(b"\x00")
        fixture_sha = fix.hexdigest()
        narration_blob = json.dumps(
            self.pw_narration_steps, sort_keys=True
        ).encode("utf-8")
        narration_sha = hashlib.sha256(narration_blob).hexdigest()
        h = hashlib.sha256()
        h.update(fn_src.encode("ascii"))
        h.update(b"\x00")
        h.update(intent_sha.encode("ascii"))
        h.update(b"\x00")
        h.update(fixture_sha.encode("ascii"))
        h.update(b"\x00")
        h.update(narration_sha.encode("ascii"))
        h.update(b"\x00")
        h.update(f"speed={self.playback_speed_factor:.6f}".encode("ascii"))
        return h.hexdigest()[:16]

    def _read_fixture_bytes(self, fixture: str) -> bytes | None:
        candidates: list[Path] = []
        p = Path(fixture)
        if p.is_absolute():
            candidates.append(p)
        else:
            if self.source_path is not None:
                candidates.append((self.source_path.parent / p).resolve())
            candidates.append(Path.cwd() / p)
        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    return c.read_bytes()
                except OSError:
                    return None
        return None


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(
    spec: str | Path,
    *,
    grep: str | None = None,
) -> Manifest:
    """Load a manifest from YAML, `path.py::test_name`, or a Playwright spec path.

    Playwright TypeScript (``.ts`` / ``.tsx`` / ``.mts`` / ``.cts``):

    - ``spec.ts::Test title`` — same as ``--manifest spec.ts --grep "Test title"``.
    - ``spec.ts`` + ``--grep`` — selects the matching test for annotation discovery.
    - ``spec.ts`` alone — tries ``spec.docgen.yaml`` sidecar, else parses
      ``test.info().annotations`` with ``type: 'docgen'`` (must match exactly
      one test unless ``grep`` is set).

    Raises `ManifestError` for invalid manifests, `FileNotFoundError` if the
    path does not exist.
    """
    if isinstance(spec, Path):
        p = spec.resolve()
        if not p.exists():
            raise FileNotFoundError(f"manifest not found: {p}")
        if _is_playwright_spec_path(p):
            return _load_playwright_ts_manifest(p, test_title=None, grep=grep)
        return _load_yaml_sidecar(p)
    text = str(spec)
    if "::" in text:
        path_part, _, tail = text.partition("::")
        path_obj = Path(path_part)
        if not path_obj.exists():
            raise FileNotFoundError(f"manifest not found: {path_obj}")
        if _is_playwright_spec_path(path_obj):
            return _load_playwright_ts_manifest(
                path_obj,
                test_title=tail.strip(),
                grep=None,
            )
        return _load_pytest_marker(path_obj, tail)
    p = Path(text)
    if not p.exists():
        raise FileNotFoundError(f"manifest not found: {p}")
    if p.suffix == ".py":
        raise ManifestError(
            "Python manifest must use 'path.py::test_name' syntax to select a test"
        )
    if _is_playwright_spec_path(p):
        return _load_playwright_ts_manifest(p, test_title=None, grep=grep)
    return _load_yaml_sidecar(p)


def _is_playwright_spec_path(path: Path) -> bool:
    return path.suffix.lower() in _PLAYWRIGHT_SPEC_SUFFIXES


def _playwright_sidecar_paths(spec_path: Path) -> list[Path]:
    """Candidate sibling manifests for ``foo.spec.ts`` (short + long stem)."""
    spec_path = spec_path.resolve()
    parent = spec_path.parent
    stem = spec_path.stem  # e.g. ``lesson.spec`` for ``lesson.spec.ts``
    names = [f"{stem}.docgen.yaml"]
    if stem.endswith(".spec"):
        names.append(f"{stem[:-len('.spec')]}.docgen.yaml")
    # De-dupe while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(parent / n)
    return out


def _find_playwright_sidecar(spec_path: Path) -> Path | None:
    for p in _playwright_sidecar_paths(spec_path):
        if p.exists():
            return p
    return None


def _load_playwright_ts_manifest(
    spec_path: Path,
    *,
    test_title: str | None,
    grep: str | None,
) -> Manifest:
    """Resolve manifest for a Node ``@playwright/test`` spec file."""
    spec_path = spec_path.resolve()
    effective_grep = (test_title or "").strip() if test_title else None
    if effective_grep is None and grep:
        effective_grep = grep.strip() or None

    sidecar = _find_playwright_sidecar(spec_path)
    if sidecar is not None:
        manifest = _load_yaml_sidecar(sidecar)
        manifest.fn_source_path = spec_path
        if manifest.kind == "playwright":
            if manifest.pw_spec is None:
                manifest.pw_spec = spec_path
            if manifest.pw_grep is None and effective_grep:
                manifest.pw_grep = effective_grep
            if manifest.pw_spec and manifest.pw_grep is None:
                raise ManifestError(
                    f"{sidecar.name}: demonstration.grep is required when using a "
                    f"TypeScript manifest entry (or pass --grep / path.ts::title)"
                )
        return manifest

    raw = _parse_ts_docgen_contract(spec_path, grep=effective_grep)
    return _coerce(raw, source_path=spec_path)


def _parse_ts_docgen_contract(spec_path: Path, *, grep: str | None) -> dict[str, Any]:
    """Extract JSON contract from ``test.info().annotations`` docgen entries."""
    src = spec_path.read_text(encoding="utf-8")
    bindings = _ts_docgen_annotation_bindings(src)
    if not bindings:
        raise ManifestError(
            f"no docgen annotation found in {spec_path.name} "
            f"(expected test.info().annotations with type 'docgen', or add "
            f"{_playwright_sidecar_paths(spec_path)[-1].name})"
        )

    if grep:
        exact = [b for b in bindings if b.test_title == grep]
        if exact:
            matches = exact
        else:
            matches = [b for b in bindings if grep in b.test_title]
        if not matches:
            raise ManifestError(
                f"no test matched --grep {grep!r} in {spec_path.name} "
                f"(available: {[b.test_title for b in bindings]})"
            )
        if len(matches) > 1:
            raise ManifestError(
                f"ambiguous --grep {grep!r}: matched {[b.test_title for b in matches]}"
            )
        chosen = matches[0]
    else:
        if len(bindings) > 1:
            titles = [b.test_title for b in bindings]
            raise ManifestError(
                f"multiple docgen annotations in {spec_path.name} without --grep "
                f"or path.ts::title (tests: {titles}). Add a sibling "
                f"{_playwright_sidecar_paths(spec_path)[0].name} "
                "or pass --grep."
            )
        chosen = bindings[0]

    desc = chosen.description_json
    if not isinstance(desc, str):
        raise ManifestError("internal: docgen description must be str")
    try:
        if desc.lstrip().startswith("{"):
            contract = _json_from_js_object_literal(desc)
        else:
            contract = json.loads(desc)
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"docgen annotation JSON is invalid near line {chosen.line}: {exc}"
        ) from exc
    if not isinstance(contract, dict):
        raise ManifestError("docgen annotation description must be a JSON object")

    demo = contract.get("demonstration")
    if isinstance(demo, dict) and demo.get("kind") == "playwright":
        # Declarative ``url`` + ``actions`` uses the in-process Python driver; only
        # add ``spec``/``grep`` for Node ``npx playwright test`` when there is no ``url``.
        if not demo.get("url"):
            if not demo.get("spec"):
                demo = dict(demo)
                demo["spec"] = str(spec_path)
            if not demo.get("grep"):
                demo = dict(demo)
                demo["grep"] = chosen.test_title
            contract = dict(contract)
            contract["demonstration"] = demo
    return contract


@dataclass
class _TsDocgenBinding:
    test_title: str
    description_json: str
    line: int


def _ts_docgen_annotation_bindings(src: str) -> list[_TsDocgenBinding]:
    """Find ``type: 'docgen'`` payloads inside each ``test('title', ...)`` block."""
    out: list[_TsDocgenBinding] = []
    # Playwright tests usually start at beginning of line; avoid matching `latest`.
    for m in re.finditer(
        r"(?:^|\n)\s*test\s*(?:\.(?:only|skip|fixme))?\s*\(\s*(['\"])((?:\\.|(?!\1).)*)\1",
        src,
        re.MULTILINE,
    ):
        raw_title = m.group(2)
        try:
            test_title = bytes(raw_title, "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            test_title = raw_title
        line_no = src.count("\n", 0, m.start()) + 1
        start = m.end()
        next_m = re.search(
            r"(?:^|\n)\s*test\s*(?:\.(?:only|skip|fixme))?\s*\(\s*['\"]",
            src[start + 1 :],
            re.MULTILINE,
        )
        block_end = start + 1 + next_m.start() if next_m else len(src)
        block = src[start:block_end]
        if not re.search(r"type\s*:\s*['\"]docgen['\"]", block, re.IGNORECASE):
            continue

        desc_json = _ts_extract_docgen_description_json(block)
        if desc_json is None:
            continue
        out.append(
            _TsDocgenBinding(
                test_title=test_title,
                description_json=desc_json,
                line=line_no,
            )
        )
    return out


def _ts_extract_docgen_description_json(block: str) -> str | None:
    """Return JSON text from ``description:`` after ``type: 'docgen'`` in *block*."""
    idx = 0
    while True:
        m_type = re.search(
            r"type\s*:\s*['\"]docgen['\"]\s*,\s*description\s*:\s*",
            block[idx:],
            re.IGNORECASE,
        )
        if not m_type:
            return None
        pos = idx + m_type.end()
        rest = block[pos:].lstrip()

        low = rest[:20].lower()
        if low.startswith("json.stringify"):
            open_paren = rest.find("(")
            if open_paren == -1:
                idx = pos
                continue
            j = open_paren + 1
            while j < len(rest) and rest[j] in " \t\n\r":
                j += 1
            if j >= len(rest) or rest[j] != "{":
                idx = pos
                continue
            end_obj = _ts_find_matching_brace(rest, j)
            if end_obj == -1:
                idx = pos
                continue
            return _strip_js_comments(rest[j : end_obj + 1])

        q = rest[0] if rest else ""
        if q in "'\"":
            end = 1
            escaped = False
            while end < len(rest):
                ch = rest[end]
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == q:
                    raw = rest[1:end]
                    try:
                        return bytes(raw, "utf-8").decode("unicode_escape")
                    except UnicodeDecodeError:
                        return raw
                end += 1
            return None
        idx = pos


def _ts_find_matching_brace(s: str, open_idx: int) -> int:
    """Return index of ``}`` matching ``{`` at *open_idx*, or -1."""
    if open_idx >= len(s) or s[open_idx] != "{":
        return -1
    depth = 0
    i = open_idx
    in_str: str | None = None
    escaped = False
    while i < len(s):
        ch = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in "'\"`":
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _strip_js_comments(fragment: str) -> str:
    """Remove // and /* */ comments from a JS object literal fragment (best-effort)."""
    out: list[str] = []
    k = 0
    n = len(fragment)
    in_str: str | None = None
    while k < n:
        ch = fragment[k]
        if in_str:
            if ch == "\\" and k + 1 < n:
                out.append(ch)
                out.append(fragment[k + 1])
                k += 2
                continue
            out.append(ch)
            if ch == in_str:
                in_str = None
            k += 1
            continue
        if ch in "'\"":
            in_str = ch
            out.append(ch)
            k += 1
            continue
        if ch == "/" and k + 1 < n:
            nxt = fragment[k + 1]
            if nxt == "/":
                k += 2
                while k < n and fragment[k] not in "\n\r":
                    k += 1
                continue
            if nxt == "*":
                k += 2
                while k + 1 < n and not (fragment[k] == "*" and fragment[k + 1] == "/"):
                    k += 1
                k = min(k + 2, n)
                continue
        out.append(ch)
        k += 1
    return "".join(out)


def _json_from_js_object_literal(fragment: str) -> dict[str, Any]:
    """Parse a JS-style object literal (possibly with trailing commas) as JSON."""
    cleaned = _strip_trailing_commas_json(_strip_js_comments(fragment))
    return json.loads(cleaned)


def _strip_trailing_commas_json(s: str) -> str:
    """Remove trailing commas before ``}`` and ``]`` (common in TS/JS)."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r",(\s*})", r"\1", s)
        s = re.sub(r",(\s*])", r"\1", s)
    return s


def _load_yaml_sidecar(path: Path) -> Manifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest must be a mapping, got: {type(raw).__name__}")
    return _coerce(raw, source_path=path)


def manifest_from_mapping(
    raw: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> Manifest:
    """Build a validated `Manifest` from the same mapping shape as a ``*.docgen.yaml``.

    For programmatic use when you are not loading YAML from disk and not using a
    Playwright ``.ts`` spec or ``path.py::test_name``. Typical cases:

    - **CLI / VHS** — ``demonstration.kind: cli`` and ``demonstration.tape`` pointing
      at a ``.tape`` file (no Playwright involved).
    - **Declarative browser** — ``demonstration.kind: playwright`` with ``url`` and
      ``actions`` (docgen drives Playwright from Python; no Node ``@playwright/test``).

    ``source_path`` resolves relative paths inside the manifest (fixtures, tape,
    optional ``spec``/``cwd``) the same way as a sidecar file next to your assets.

    Raises `ManifestError` if the mapping violates the schema.
    """
    return _coerce(raw, source_path=source_path)


def _load_pytest_marker(path: Path, test_name: str) -> Manifest:
    """Read `@pytest.mark.docgen(...)` decorator on `test_name` via `ast`.

    Walking the AST avoids two common failure modes:
      - `regex over source` matches markdown text inside module docstrings
        that talk *about* the marker (F7).
      - `import` / `exec` runs the test file's top-level code (and its
        dependencies), which is unsafe and slow during static read.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        raise ManifestError(f"could not parse {path}: {exc}") from exc

    target_fn: ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == test_name:
            target_fn = node
            break
    if target_fn is None:
        raise ManifestError(f"function not found in {path}: {test_name}")

    marker_call: ast.Call | None = None
    for dec in target_fn.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        if _is_pytest_mark_docgen(dec.func):
            marker_call = dec
            break
    if marker_call is None:
        raise ManifestError(
            f"{path}::{test_name} is missing @pytest.mark.docgen(...) decorator"
        )

    raw: dict[str, Any] = {}
    for kw in marker_call.keywords:
        if kw.arg is None:
            continue
        try:
            raw[kw.arg] = ast.literal_eval(kw.value)
        except (ValueError, SyntaxError) as exc:
            raise ManifestError(
                f"@pytest.mark.docgen({kw.arg}=...) must be a literal: {exc}"
            ) from exc
    return _coerce(raw, source_path=path)


def _is_pytest_mark_docgen(node: ast.AST) -> bool:
    """Return True if `node` represents `pytest.mark.docgen` (or the bare
    `docgen` mark imported from `pytest.mark`)."""
    if isinstance(node, ast.Attribute) and node.attr == "docgen":
        if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
            inner = node.value.value
            if isinstance(inner, ast.Name) and inner.id == "pytest":
                return True
    return False


def _coerce(raw: dict[str, Any], *, source_path: Path | None = None) -> Manifest:
    """Validate `raw` and produce a normalised `Manifest`.

    Raises `ManifestError` for any schema violation.
    """
    for required in ("identifier", "intent"):
        if required not in raw or not str(raw.get(required, "")).strip():
            raise ManifestError(f"manifest missing required field: '{required}'")

    demonstration = raw.get("demonstration")
    if not isinstance(demonstration, dict) or "kind" not in demonstration:
        raise ManifestError("manifest missing required field: 'demonstration.kind'")
    kind = str(demonstration.get("kind", "")).strip()
    if kind not in {"playwright", "cli"}:
        raise ManifestError(
            f"demonstration.kind must be 'playwright' or 'cli', got: '{kind}'"
        )

    url = demonstration.get("url")
    if url is not None:
        url = str(url).strip() or None

    spec_raw = demonstration.get("spec")
    grep_raw = demonstration.get("grep")
    pw_cwd_raw = demonstration.get("cwd")
    pw_base_url = demonstration.get("base_url")
    if pw_base_url is not None:
        pw_base_url = str(pw_base_url).strip() or None

    tape_raw = demonstration.get("tape")

    pw_spec: Path | None = None
    pw_grep: str | None = None
    pw_cwd: Path | None = None
    cli_tape: Path | None = None

    if kind == "playwright":
        if spec_raw is not None:
            pw_spec = Path(str(spec_raw).strip())
            if not pw_spec.is_absolute() and source_path is not None:
                pw_spec = (source_path.parent / pw_spec).resolve()
            elif not pw_spec.is_absolute():
                pw_spec = Path.cwd() / pw_spec
                pw_spec = pw_spec.resolve()
        if grep_raw is not None and str(grep_raw).strip():
            pw_grep = str(grep_raw).strip()
        if pw_spec is not None and not pw_grep:
            raise ManifestError(
                "demonstration.grep is required when demonstration.spec is set"
            )
        if pw_cwd_raw is not None:
            pw_cwd = Path(str(pw_cwd_raw).strip())
            if not pw_cwd.is_absolute() and source_path is not None:
                pw_cwd = (source_path.parent / pw_cwd).resolve()
            elif not pw_cwd.is_absolute():
                pw_cwd = (Path.cwd() / pw_cwd).resolve()

    if kind == "cli":
        if tape_raw is None or not str(tape_raw).strip():
            raise ManifestError("demonstration.tape is required for kind: cli")
        cli_tape = Path(str(tape_raw).strip())
        if not cli_tape.is_absolute() and source_path is not None:
            cli_tape = (source_path.parent / cli_tape).resolve()
        elif not cli_tape.is_absolute():
            cli_tape = (Path.cwd() / cli_tape).resolve()

    actions_raw = demonstration.get("actions") or []
    if not isinstance(actions_raw, list):
        raise ManifestError("demonstration.actions must be a list")
    actions = [Action.from_mapping(a) for a in actions_raw]

    pw_narration_steps: list[dict[str, str]] = []
    narration_steps_raw = raw.get("narration_steps")
    if narration_steps_raw is not None:
        if not isinstance(narration_steps_raw, list):
            raise ManifestError("narration_steps must be a list")
        for i, step in enumerate(narration_steps_raw):
            if not isinstance(step, dict):
                raise ManifestError(
                    f"narration_steps[{i}] must be a mapping, got: {type(step).__name__}"
                )
            api_name = step.get("api_name")
            say = step.get("say")
            if not isinstance(api_name, str) or not api_name.strip():
                raise ManifestError(
                    f"narration_steps[{i}].api_name must be a non-empty string"
                )
            if not isinstance(say, str) or not say.strip():
                raise ManifestError(
                    f"narration_steps[{i}].say must be a non-empty string"
                )
            pw_narration_steps.append(
                {"api_name": api_name.strip(), "say": say.strip()}
            )

    setup = raw.get("setup") or {}
    fixtures_raw = setup.get("fixtures", []) if isinstance(setup, dict) else []
    if not isinstance(fixtures_raw, list):
        raise ManifestError("setup.fixtures must be a list of paths")
    fixtures = [str(f) for f in fixtures_raw]

    assertions_raw = raw.get("assertions_to_surface") or []
    if not isinstance(assertions_raw, list):
        raise ManifestError("assertions_to_surface must be a list of strings")
    assertions: list[str] = []
    for a in assertions_raw:
        s = str(a)
        if len(s) > 60:
            raise ManifestError(
                f"assertions_to_surface entries must be ≤ 60 chars: '{s[:80]}'"
            )
        assertions.append(s)

    output_budget = raw.get("output_budget") or {}
    if not isinstance(output_budget, dict):
        raise ManifestError("output_budget must be a mapping")
    duration = int(output_budget.get("duration_seconds", DEFAULT_DURATION_SECONDS))
    if duration > HARD_CAP_SECONDS:
        raise ManifestError(
            f"output_budget.duration_seconds={duration} exceeds the 60s hard cap"
        )
    if duration <= 0:
        raise ManifestError("output_budget.duration_seconds must be positive")
    resolution = str(output_budget.get("resolution", DEFAULT_RESOLUTION))
    if not RESOLUTION_RE.match(resolution):
        raise ManifestError(
            f"output_budget.resolution must match WxH (e.g. 1280x720), got: '{resolution}'"
        )

    speed_raw = output_budget.get("playback_speed_factor", DEFAULT_PLAYBACK_SPEED_FACTOR)
    try:
        speed_factor = float(speed_raw)
    except (TypeError, ValueError) as exc:
        raise ManifestError(
            f"output_budget.playback_speed_factor must be a number, got: {speed_raw!r}"
        ) from exc
    if not (MIN_PLAYBACK_SPEED_FACTOR <= speed_factor <= MAX_PLAYBACK_SPEED_FACTOR):
        raise ManifestError(
            f"output_budget.playback_speed_factor={speed_factor} outside "
            f"[{MIN_PLAYBACK_SPEED_FACTOR}, {MAX_PLAYBACK_SPEED_FACTOR}]"
        )

    fn_source_path: Path | None = source_path
    if pw_spec is not None:
        fn_source_path = pw_spec
    elif cli_tape is not None:
        fn_source_path = cli_tape

    if kind == "playwright" and pw_spec is not None:
        if url:
            raise ManifestError(
                "use either demonstration.spec (Playwright test) or demonstration.url, not both"
            )
        if actions:
            raise ManifestError(
                "demonstration.actions must be empty when demonstration.spec is set"
            )
    if kind == "cli" and cli_tape is not None and actions:
        raise ManifestError(
            "demonstration.actions must be empty for kind: cli (drive the demo via the .tape)"
        )

    return Manifest(
        identifier=str(raw["identifier"]).strip(),
        intent=str(raw["intent"]).strip(),
        kind=kind,
        url=url,
        actions=actions,
        fixtures=fixtures,
        assertions_to_surface=assertions,
        duration_seconds=duration,
        resolution=resolution,
        playback_speed_factor=speed_factor,
        source_path=source_path,
        fn_source_path=fn_source_path,
        pw_spec=pw_spec,
        pw_grep=pw_grep,
        pw_cwd=pw_cwd,
        pw_base_url=pw_base_url,
        pw_narration_steps=pw_narration_steps,
        cli_tape=cli_tape,
    )


# ---------------------------------------------------------------------------
# Action -> Playwright source rendering
# ---------------------------------------------------------------------------


def _render_action(action: Action) -> str:
    """Translate one action into a single line of Playwright sync_api code.

    Selectors and values are passed through `repr()` so embedded quotes are
    escaped without any string-template gymnastics (F6).
    """
    p = action.params
    if action.kind == "goto":
        url = p.get("url") or ""
        return f"page.goto({url!r}, wait_until=\"networkidle\")"
    if action.kind == "click":
        return f"page.click({p['selector']!r})"
    if action.kind == "fill":
        return f"page.fill({p['selector']!r}, {p['value']!r})"
    if action.kind == "type":
        delay = int(p.get("delay_ms", 40))
        sel = p["selector"]
        val = p["value"]
        return (
            f"page.click({sel!r}); "
            f"page.keyboard.type({val!r}, delay={delay})"
        )
    if action.kind == "wait_for":
        timeout = int(p.get("timeout_ms", 10000))
        return f"page.wait_for_selector({p['selector']!r}, timeout={timeout})"
    if action.kind == "wait_for_text":
        timeout = int(p.get("timeout_ms", 10000))
        sel = p["selector"]
        text = p["text"]
        return (
            f"page.locator({sel!r}).filter(has_text={text!r}).first."
            f"wait_for(state=\"visible\", timeout={timeout})"
        )
    if action.kind == "wait":
        return f"page.wait_for_timeout({int(p['ms'])})"
    if action.kind == "screenshot":
        return f"page.screenshot(path={str(p['path'])!r})"
    raise ManifestError(f"unsupported action kind: '{action.kind}'")


def generate_capture_script(manifest: Manifest, *, output_path: Path) -> str:
    """Generate a standalone Playwright capture script for `manifest`.

    This is exposed (rather than being purely internal) so consumers can
    inspect the generated script and so unit tests can assert that the
    output compiles without launching Playwright.
    """
    width, height = manifest.viewport
    initial_url = manifest.url or ""
    action_lines = [_render_action(a) for a in manifest.actions]
    overlay_assertions = json.dumps(manifest.assertions_to_surface)
    body = "\n            ".join(action_lines) if action_lines else "pass"
    return _SCRIPT_TEMPLATE.format(
        output_path=str(output_path),
        width=width,
        height=height,
        url=initial_url,
        body=body,
        overlay_assertions=overlay_assertions,
    )


_SCRIPT_TEMPLATE = '''"""Auto-generated Playwright capture script (docgen demo-function)."""

from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    output_path = Path({output_path!r})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={{"width": {width}, "height": {height}}},
            record_video_dir=str(output_path.parent),
            record_video_size={{"width": {width}, "height": {height}}},
        )
        page = context.new_page()
        try:
            initial_url = {url!r}
            if initial_url:
                page.goto(initial_url, wait_until="networkidle")
            {body}
        finally:
            video_path = page.video.path() if page.video else None
            context.close()
            browser.close()
        if video_path:
            Path(video_path).rename(output_path)


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_lookup(cache_dir: Path, cache_key: str, output_dir: Path) -> bool:
    """If a cache entry exists, copy artifacts into `output_dir`. Returns hit."""
    entry = cache_dir / cache_key
    if not entry.exists() or not entry.is_dir():
        return False
    for name in CACHED_ARTIFACTS:
        f = entry / name
        if not f.exists() or f.stat().st_size == 0:
            return False
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in CACHED_ARTIFACTS:
        shutil.copy2(entry / name, output_dir / name)
    return True


def _cache_store(cache_dir: Path, cache_key: str, output_dir: Path) -> None:
    entry = cache_dir / cache_key
    entry.mkdir(parents=True, exist_ok=True)
    for name in CACHED_ARTIFACTS:
        src = output_dir / name
        if src.exists():
            shutil.copy2(src, entry / name)


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------


def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise ToolingMissingError(
            "ffmpeg not found on PATH",
            install_hint="apt-get install -y ffmpeg  # or: brew install ffmpeg",
        )


def _ensure_ffprobe() -> None:
    if shutil.which("ffprobe") is None:
        raise ToolingMissingError(
            "ffprobe not found on PATH",
            install_hint="apt-get install -y ffmpeg  # or: brew install ffmpeg",
        )


def _transcode_to_mp4(src: Path, dst: Path, *, width: int, height: int) -> None:
    """Transcode a video to MP4 (libx264, yuv420p, +faststart) at WxH."""
    _ensure_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg transcode failed: {proc.stderr[-400:]}"
        )


def _extract_poster(video: Path, poster: Path) -> None:
    """Extract the last frame of `video` into `poster` (PNG)."""
    _ensure_ffmpeg()
    poster.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-sseof", "-0.1",
        "-i", str(video),
        "-update", "1",
        "-frames:v", "1",
        str(poster),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg poster extraction failed: {proc.stderr[-400:]}"
        )


def _probe_audio_ms(audio_path: Path) -> int | None:
    if shutil.which("ffprobe") is None:
        return None
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(audio_path),
        ],
        capture_output=True, text=True,
    )
    try:
        return int(round(float(proc.stdout.strip()) * 1000))
    except ValueError:
        return None


def _mux_audio(video: Path, audio: Path, dst: Path) -> None:
    _ensure_ffmpeg()
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {proc.stderr[-400:]}")


def _mux_audio_padded(video: Path, audio: Path, dst: Path) -> None:
    """Mux audio over video; pad audio with trailing silence to match video length.

    Used when the visual was retimed (slowed) — the one-line TTS narration plays
    at natural pace and sits inside a longer clip, with silence after the words
    end. Final length == video length (not ``min(video, audio)`` like
    :func:`_mux_audio`).
    """
    _ensure_ffmpeg()
    video_dur = _probe_video_duration_sec(video) or 0.0
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex", "[1:a]apad[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
    ]
    if video_dur > 0:
        cmd += ["-t", f"{video_dur:.3f}"]
    cmd += ["-movflags", "+faststart", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg padded mux failed: {proc.stderr[-400:]}")


def _keyframe_extract_params_from_environ() -> tuple[float, int]:
    """Return ``(interval_sec, max_count)`` for vision keyframe sampling.

    Used by :func:`_align_visual_to_narration` so subprocess-based tests (or
    low-quota local runs) can shrink the batched vision request without YAML
    changes. Defaults match :func:`docgen.pf_keyframes.extract_candidates`.

    Environment (optional, subprocess-visible):

    * ``DOCGEN_KEYFRAME_INTERVAL_SEC`` — float, default ``0.20``, floored at ``0.05``.
    * ``DOCGEN_KEYFRAME_MAX_COUNT`` — int, default ``30``, minimum ``2``.
    """
    interval_sec = 0.20
    max_count = 30
    raw_i = os.environ.get("DOCGEN_KEYFRAME_INTERVAL_SEC", "").strip()
    if raw_i:
        try:
            interval_sec = max(0.05, float(raw_i))
        except ValueError:
            pass
    raw_m = os.environ.get("DOCGEN_KEYFRAME_MAX_COUNT", "").strip()
    if raw_m:
        try:
            max_count = max(2, int(raw_m))
        except ValueError:
            pass
    return interval_sec, max_count


def _align_visual_to_narration(
    *,
    source_visual: Path,
    raw_timeline: list[dict[str, Any]],
    work_dir: Path,
    width: int,
    height: int,
    voice: str = "coral",
    tts_model: str = "gpt-4o-mini-tts",
    tail_pad_ms: int = 600,
) -> tuple[Path, "NarrationResult", list[dict[str, Any]]]:
    """Audio-driven slideshow: ONE TTS + Whisper + vision-picked stills.

    Pipeline (audio is the master clock — never spliced, never re-mixed):

    1. Concatenate every ``raw_timeline[*].say`` into one paragraph and
       synthesise it as a single MP3. Natural prosody and inter-sentence
       breath fall out for free.
    2. Run Whisper with word-level timestamps over that MP3 and walk the
       word stream, greedily matching each step to its tokens. Each step
       gets a ``(start_ms, end_ms)`` window inside the audio.
    3. Sample candidate frames from ``source_visual`` at uniform intervals
       (``pf_keyframes.extract_candidates``).
    4. A vision LLM (``pf_keyframes.match_steps_to_keyframes``) picks the
       SINGLE candidate that best shows what each narration line describes.
       This is what makes the slideshow correct even when Playwright's
       screencast warmup ate the earliest frames — the LLM simply doesn't
       pick a frame whose visible state contradicts the line.
    5. Build a slideshow MP4: each chosen still held for its line's
       Whisper-aligned duration. The single MP3 is muxed under the
       slideshow as the LAST step (handled by the orchestrator).

    Returns ``(slideshow_path, narration_result, target_timeline)``.
    ``target_timeline[i].t_start_ms`` is the whisper-derived start time
    of line ``i`` inside the muxed audio, ready for caption burning at
    ``speed_factor=1.0``.
    """
    from docgen.pf_align import (
        StepTiming,
        synthesize_full_narration,
        whisper_align_steps,
    )
    from docgen.pf_keyframes import (
        extract_candidates,
        match_steps_to_keyframes,
    )

    timeline = [t for t in raw_timeline if t.get("say")]
    if not timeline:
        raise RuntimeError(
            "audio-driven sync requires a non-empty say-timeline"
        )
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    narration_path = work_dir / "narration.mp3"
    transcript = synthesize_full_narration(
        timeline,
        narration_path,
        voice=voice,
        model=tts_model,
        tts_synthesize=_tts_synthesize,
    )
    audio_total_ms = _probe_audio_ms(narration_path) or 0
    if audio_total_ms <= 0:
        raise RuntimeError(
            f"narration audio probed as 0ms ({narration_path}); cannot align"
        )

    step_timings: list[StepTiming] = whisper_align_steps(
        narration_path,
        timeline,
        transcript_prompt=transcript,
    )
    if len(step_timings) != len(timeline):
        raise RuntimeError(
            f"whisper produced {len(step_timings)} step timings, "
            f"expected {len(timeline)}"
        )

    k_interval, k_max = _keyframe_extract_params_from_environ()
    candidates = extract_candidates(
        source_visual,
        work_dir / "keyframe_candidates",
        interval_sec=k_interval,
        max_count=k_max,
    )
    chosen = match_steps_to_keyframes(candidates, timeline)
    if len(chosen) != len(timeline):
        raise RuntimeError(
            f"vision matcher returned {len(chosen)} frames, "
            f"expected {len(timeline)}"
        )
    # Debug log: which candidate index the vision LLM picked for each
    # narration step. The slideshow's quality depends on this mapping
    # being non-degenerate (all-same-index → "stuck" demo); logging it
    # at INFO level makes that obvious without requiring keep-tmp.
    _log_keyframe_picks(timeline, chosen, candidates)

    # Per-step visible duration: each frame is held until the matching
    # narration line ENDS in audio. The very last frame is held a bit
    # longer (``tail_pad_ms``) so the final state lingers past the last
    # spoken word before the audio fades.
    durations_ms: list[int] = []
    target_offsets_ms: list[int] = []
    cumulative_ms = 0
    prev_anchor_audio_ms = 0
    for i, t in enumerate(step_timings):
        line_end_audio_ms = t.end_ms
        if i == len(step_timings) - 1:
            line_end_audio_ms = max(line_end_audio_ms, audio_total_ms) + tail_pad_ms
        dur_ms = max(50, line_end_audio_ms - prev_anchor_audio_ms)
        durations_ms.append(dur_ms)
        offset_into_seg = max(0, t.start_ms - prev_anchor_audio_ms)
        target_offsets_ms.append(cumulative_ms + offset_into_seg)
        cumulative_ms += dur_ms
        prev_anchor_audio_ms = line_end_audio_ms

    slideshow_path = work_dir / "visual_slideshow.mp4"
    _build_slideshow(
        frames=[c.path for c in chosen],
        durations_sec=[d / 1000.0 for d in durations_ms],
        out_video=slideshow_path,
        width=width,
        height=height,
        work_dir=work_dir / "slideshow",
    )

    target_timeline: list[dict[str, Any]] = [
        {
            "say": str(timeline[i]["say"]),
            "t_start_ms": int(target_offsets_ms[i]),
            "api_name": timeline[i].get("api_name"),
        }
        for i in range(len(timeline))
    ]
    narration_result = NarrationResult(
        audio_path=narration_path,
        voice=voice,
        model=tts_model,
        ms=audio_total_ms,
    )
    return slideshow_path, narration_result, target_timeline


def _log_keyframe_picks(
    timeline: list[dict[str, Any]],
    chosen: list[Any],
    candidates: list[Any],
) -> None:
    """Print the vision LLM's keyframe pick for each narration step.

    Surfaces the failure mode where the LLM picks the same candidate for
    every step (slideshow appears frozen on one frame). When the picks
    are non-degenerate this is a single concise dump; when they're
    degenerate the pattern is immediately visible in stderr.
    """
    n_unique = len({c.index for c in chosen})
    sys.stderr.write(
        f"[docgen] vision LLM keyframe picks "
        f"({n_unique} unique / {len(chosen)} steps from "
        f"{len(candidates)} candidates):\n"
    )
    for i, (step, frame) in enumerate(zip(timeline, chosen)):
        say = str(step.get("say") or "").strip()
        sys.stderr.write(
            f"  step {i}: candidate #{frame.index:02d} "
            f"(t={frame.t_seconds:.2f}s) ← {say!r}\n"
        )
    if n_unique == 1:
        sys.stderr.write(
            "[docgen] WARNING: all narration steps map to the SAME "
            "candidate frame — slideshow will appear frozen. "
            "Re-run with DOCGEN_DEBUG_KEEP_TMP=1 to inspect "
            "keyframe_candidates/ and tune pf_keyframes._SYSTEM_PROMPT.\n"
        )


def _build_slideshow(
    *,
    frames: list[Path],
    durations_sec: list[float],
    out_video: Path,
    width: int,
    height: int,
    work_dir: Path,
) -> None:
    """Concat per-step still images into a CFR slideshow MP4.

    For each ``(frame_path, duration_sec)`` pair we render a tiny MP4 of
    the still looped for ``duration_sec`` (CFR 30, libx264, yuv420p).
    All sub-clips share codec / pixel format / framerate, so the final
    concat-demuxer pass runs without re-encode.

    Why per-image clips and not a single ``concat=`` filter graph? The
    demuxer-without-reencode path is dramatically faster on long
    slideshows AND lets us debug a bad slide by playing the offending
    sub-clip in isolation. The cost (one ffmpeg fork per slide) is
    negligible for the 5-15 slide demos this pipeline produces.

    The output has no audio track — the orchestrator muxes the single
    Whisper-aligned MP3 underneath as the LAST step.
    """
    if not frames:
        raise ValueError("no frames provided to slideshow builder")
    if len(frames) != len(durations_sec):
        raise ValueError(
            f"frames/durations length mismatch: "
            f"{len(frames)} frames vs {len(durations_sec)} durations"
        )
    _ensure_ffmpeg()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    seg_files: list[Path] = []
    for i, (frame, dur) in enumerate(zip(frames, durations_sec)):
        seg_dur = max(0.05, float(dur))
        seg_path = work_dir / f"slide_{i:03d}.mp4"
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(frame),
            "-t",
            f"{seg_dur:.3f}",
            "-vf",
            f"scale={int(width)}:{int(height)},setsar=1,format=yuv420p,fps=30",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(seg_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg slideshow segment failed "
                f"(slide {i}, frame={frame.name}, dur={seg_dur:.3f}s): "
                f"{proc.stderr[-500:]}"
            )
        seg_files.append(seg_path)

    concat_list = work_dir / "slideshow_concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in seg_files),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c:v",
        "copy",
        "-movflags",
        "+faststart",
        str(out_video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg slideshow concat failed: {proc.stderr[-500:]}"
        )


def _extend_video_with_freeze(
    video_in: Path,
    video_out: Path,
    *,
    target_seconds: float,
    tail_padding_seconds: float = 0.5,
) -> None:
    """Extend ``video_in`` to ``target_seconds`` by repeating the last frame.

    No-op (copy) when the input is already at least ``target_seconds`` long.
    The ``tail_padding_seconds`` is added on top of ``target_seconds`` so the
    final state lingers briefly after narration ends instead of cutting to
    black abruptly.

    Implementation uses ffmpeg's ``tpad=stop_mode=clone:stop_duration=<delta>``
    which clones the last decoded frame; reliable in ffmpeg 4.3+.
    """
    _ensure_ffmpeg()
    src_sec = _probe_video_duration_sec(video_in) or 0.0
    needed = max(0.0, float(target_seconds) + float(tail_padding_seconds) - src_sec)
    if needed <= 1e-3:
        shutil.copy2(video_in, video_out)
        return
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-vf", f"tpad=stop_mode=clone:stop_duration={needed:.3f}",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(video_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg freeze-extend failed: {proc.stderr[-400:]}"
        )


def _retime_video(video_in: Path, video_out: Path, *, speed_factor: float) -> None:
    """Retime video by ``speed_factor`` via ffmpeg ``setpts``.

    ``speed_factor < 1.0`` slows playback (longer duration); ``> 1.0`` speeds it
    up. Audio is dropped (``-an``) — the caller adds narration via
    :func:`_mux_audio_padded` so the video length wins.
    """
    if abs(speed_factor - 1.0) < 1e-6:
        shutil.copy2(video_in, video_out)
        return
    if speed_factor <= 0:
        raise RuntimeError(f"playback_speed_factor must be > 0, got {speed_factor}")
    _ensure_ffmpeg()
    setpts_factor = 1.0 / float(speed_factor)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-filter:v", f"setpts={setpts_factor:.6f}*PTS",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(video_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg retime failed: {proc.stderr[-400:]}")


def _probe_video_duration_sec(path: Path) -> float | None:
    _ensure_ffprobe()
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def _vtt_from_assertions(lines: list[str], *, total_sec: float) -> str:
    """Build WebVTT with timed cues spread across the clip."""
    n = len(lines)
    if n == 0:
        return "WEBVTT\n\n"
    total_sec = max(1.0, total_sec)
    chunk = total_sec / n
    parts = ["WEBVTT", ""]

    def fmt(ts: float) -> str:
        h = int(ts // 3600)
        m = int((ts % 3600) // 60)
        s = ts % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    for i, text in enumerate(lines):
        a = i * chunk
        b = total_sec if i == n - 1 else (i + 1) * chunk
        parts.append(str(i + 1))
        parts.append(f"{fmt(a)} --> {fmt(b)}")
        parts.append(text.replace("&", "&amp;").replace("<", "&lt;"))
        parts.append("")
    return "\n".join(parts) + "\n"


def _video_has_audio_stream(path: Path) -> bool:
    _ensure_ffprobe()
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return bool(proc.stdout.strip())


def _burn_captions_from_vtt(
    video_in: Path,
    video_out: Path,
    vtt_path: Path,
) -> None:
    """Burn an existing WebVTT file as bottom subtitles via ffmpeg."""
    _ensure_ffmpeg()
    sub_path = str(vtt_path.resolve()).replace("\\", "\\\\").replace(":", "\\:")
    if _video_has_audio_stream(video_in):
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-vf", f"subtitles={sub_path}",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(video_out),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_in),
            "-vf", f"subtitles={sub_path}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            "-movflags", "+faststart",
            str(video_out),
        ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg subtitle burn-in failed: {proc.stderr[-500:]}"
        )


def _burn_assertion_captions(
    video_in: Path,
    video_out: Path,
    assertions: list[str],
    *,
    work_dir: Path,
) -> None:
    """Overlay `assertions` as bottom subtitles (WebVTT via ffmpeg).

    Used when there is no per-action timeline. Cues are spread evenly across
    the clip — see :func:`_burn_timed_captions` for action-aligned captions.
    """
    if not assertions:
        shutil.copy2(video_in, video_out)
        return
    dur = _probe_video_duration_sec(video_in) or 30.0
    vtt_path = work_dir / "assertions.vtt"
    vtt_path.write_text(
        _vtt_from_assertions(assertions, total_sec=dur),
        encoding="utf-8",
    )
    _burn_captions_from_vtt(video_in, video_out, vtt_path)


def _vtt_from_timeline(
    timeline: list[dict[str, Any]],
    *,
    speed_factor: float,
    total_sec: float,
) -> str:
    """Build WebVTT cues from a captured action timeline.

    Each entry is ``{kind, say, t_start_ms, t_end_ms}``. Timestamps are
    relative to the *original* recording wall clock; we scale by
    ``1 / speed_factor`` so cues align with the slowed playback. Each
    captioned action is shown from its start until the next captioned
    action (or video end), so viewers always have something on screen.
    """
    speed = max(speed_factor, 1e-6)
    captioned: list[tuple[float, str]] = []
    for entry in timeline:
        text = entry.get("say")
        if not text:
            continue
        t_start = (entry.get("t_start_ms", 0) / 1000.0) / speed
        captioned.append((t_start, str(text)))
    if not captioned:
        return "WEBVTT\n\n"
    captioned.sort(key=lambda x: x[0])
    parts = ["WEBVTT", ""]

    def fmt(ts: float) -> str:
        ts = max(0.0, min(ts, total_sec))
        h = int(ts // 3600)
        m = int((ts % 3600) // 60)
        s = ts % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

    for i, (t_start, text) in enumerate(captioned):
        t_end = captioned[i + 1][0] if i + 1 < len(captioned) else total_sec
        # Cap at video end and at the next cue's start (no overlap / stacking).
        t_end = min(t_end, total_sec)
        # Ensure a non-zero cue duration even when actions fire back-to-back.
        if t_end <= t_start:
            t_end = t_start + 0.05
        parts.append(str(i + 1))
        parts.append(f"{fmt(t_start)} --> {fmt(t_end)}")
        parts.append(text.replace("&", "&amp;").replace("<", "&lt;"))
        parts.append("")
    return "\n".join(parts) + "\n"


def _burn_timed_captions(
    video_in: Path,
    video_out: Path,
    timeline: list[dict[str, Any]],
    *,
    speed_factor: float,
    work_dir: Path,
) -> None:
    """Burn WebVTT cues built from ``timeline`` onto ``video_in``.

    Falls back to a no-op copy when no entry has ``say``.
    """
    if not any(entry.get("say") for entry in timeline):
        shutil.copy2(video_in, video_out)
        return
    dur = _probe_video_duration_sec(video_in) or 30.0
    vtt_text = _vtt_from_timeline(
        timeline,
        speed_factor=speed_factor,
        total_sec=dur,
    )
    vtt_path = work_dir / "timeline.vtt"
    vtt_path.write_text(vtt_text, encoding="utf-8")
    _burn_captions_from_vtt(video_in, video_out, vtt_path)


def _trim_video_head(path: Path, *, max_seconds: float) -> None:
    """Trim in place when duration exceeds ``max_seconds`` (copy streams)."""
    dur = _probe_video_duration_sec(path)
    if dur is None or dur <= max_seconds + 0.05:
        return
    _ensure_ffmpeg()
    tmp = path.with_suffix(path.suffix + ".trim.tmp.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-ss", "0",
        "-t", str(max_seconds),
        "-i", str(path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg trim failed: {proc.stderr[-400:]}")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------


@dataclass
class NarrationResult:
    audio_path: Path
    voice: str
    model: str
    ms: int


_TTS_INSTRUCTIONS = (
    "You are narrating a per-function code demo. Speak in a calm, "
    "professional tone. One sentence."
)


def _tts_synthesize(
    text: str,
    out_path: Path,
    *,
    voice: str,
    model: str,
) -> None:
    """Low-level OpenAI TTS call: writes ``text`` as MP3 to ``out_path``.

    Auth failures (invalid / revoked / scoped-out key) are re-raised as
    :class:`ToolingMissingError` so the renderer fails fast with a clear
    install hint instead of producing a silent video or surfacing an
    SDK-specific exception. :class:`openai.RateLimitError` is retried with
    backoff so bursts / parallel runs don't fail on the first 429.
    """
    import openai

    client = openai.OpenAI()

    def _call() -> None:
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            instructions=_TTS_INSTRUCTIONS,
        )
        response.stream_to_file(str(out_path))

    try:
        call_with_rate_limit_retries(_call)
    except openai.AuthenticationError as exc:
        raise ToolingMissingError(
            f"OpenAI rejected OPENAI_API_KEY (authentication failed): {exc}",
            install_hint=(
                "Set a valid OPENAI_API_KEY (export OPENAI_API_KEY=sk-...) "
                "or pass --no-narration to opt into a silent clip."
            ),
        ) from exc
    except openai.PermissionDeniedError as exc:
        raise ToolingMissingError(
            f"OPENAI_API_KEY lacks required permissions for "
            f"{model}/{voice} TTS: {exc}",
            install_hint=(
                "Use a key whose project has access to "
                "audio.speech.create + the requested model."
            ),
        ) from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"OpenAI TTS network error: {exc} — re-run when connectivity is "
            "restored, or pass --no-narration to opt into a silent clip."
        ) from exc


def _generate_narration(
    intent: str,
    work_dir: Path,
    *,
    voice: str = "coral",
    model: str = "gpt-4o-mini-tts",
) -> NarrationResult:
    """Generate a single-clip narration MP3 from ``intent``.

    Used when no action provides a ``say`` — the whole clip plays a single
    sentence. When a say-timeline is available the orchestrator instead
    routes through :func:`_align_visual_to_narration`, which performs
    ONE TTS pass over all lines, uses Whisper word timings to set per-step
    durations, and assembles a vision-LLM keyframe slideshow.
    """
    out = work_dir / "narration.mp3"
    _tts_synthesize(intent, out, voice=voice, model=model)
    ms = _probe_audio_ms(out) or 0
    return NarrationResult(audio_path=out, voice=voice, model=model, ms=ms)


# ---------------------------------------------------------------------------
# Render orchestration
# ---------------------------------------------------------------------------


@dataclass
class RenderResult:
    output_dir: Path
    cache_status: str  # "hit" or "miss"
    manifest: Manifest
    narration: NarrationResult | None = None


def render(
    manifest: Manifest,
    output_dir: Path,
    *,
    cache_dir: Path | None = None,
    no_narration: bool = False,
    stderr=None,
) -> RenderResult:
    """Render one demo-function manifest into `output_dir`.

    Raises:
        PlaceholderManifest: if `kind=playwright` and no `url` was provided.
        ToolingMissingError: if a required external tool (ffmpeg / playwright)
            is missing.
        ManifestError / RuntimeError: on render failures.
    """
    if stderr is None:
        stderr = sys.stderr
    output_dir = Path(output_dir).resolve()

    is_pw_actions = manifest.kind == "playwright" and manifest.pw_spec is None
    if is_pw_actions and not manifest.url:
        raise PlaceholderManifest(
            f"manifest is a placeholder (no demonstration.url): "
            f"{manifest.identifier}"
        )

    # Fail-loud key check BEFORE expensive capture/transcode work — refuse to
    # waste a Chromium launch + ffmpeg pass on a run that will then have no
    # narration to mux. ``--no-narration`` is the explicit silent opt-in.
    if not no_narration and not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ToolingMissingError(
            "OPENAI_API_KEY is not set — refusing to emit a silent "
            "demo. Set the key to generate narration, or pass "
            "--no-narration to explicitly opt into a visual-only clip.",
            install_hint="export OPENAI_API_KEY=sk-...",
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    cache_key = manifest.cache_key
    if cache_dir is not None:
        cache_dir = Path(cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        if _cache_lookup(cache_dir, cache_key, output_dir):
            (output_dir / "cache-status.txt").write_text("hit\n", encoding="utf-8")
            return RenderResult(
                output_dir=output_dir,
                cache_status="hit",
                manifest=manifest,
            )

    rendered_mp4 = output_dir / "rendered.mp4"
    poster_png = output_dir / "poster.png"
    fragment_txt = output_dir / "fragment.txt"
    manifest_json = output_dir / "manifest.json"
    cache_status_txt = output_dir / "cache-status.txt"

    width, height = manifest.viewport

    # ``DOCGEN_DEBUG_KEEP_TMP=1`` preserves the per-render scratch directory
    # ( normally cleaned up after success ) so the candidate keyframes,
    # vision LLM picks, slideshow segments, and intermediate audio/video
    # are inspectable when debugging matcher / sync issues. Path is logged
    # to stderr at the start of the run.
    keep_tmp = bool(os.environ.get("DOCGEN_DEBUG_KEEP_TMP", "").strip())
    tmp_ctx: Any
    if keep_tmp:
        tmp_root = tempfile.mkdtemp(prefix="docgen-demo-")
        if stderr is not None:
            stderr.write(
                f"[docgen] DOCGEN_DEBUG_KEEP_TMP=1 → preserving scratch dir: {tmp_root}\n"
            )
        else:
            sys.stderr.write(
                f"[docgen] DOCGEN_DEBUG_KEEP_TMP=1 → preserving scratch dir: {tmp_root}\n"
            )

        class _NoopCtx:
            def __enter__(self) -> str:
                return tmp_root

            def __exit__(self, *_a: Any) -> None:
                return None

        tmp_ctx = _NoopCtx()
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="docgen-demo-")

    with tmp_ctx as tmp:
        tmp_path = Path(tmp)
        _stage_fixtures(manifest, tmp_path, stderr=stderr)

        timeline_path = tmp_path / "timeline.json"
        timeline: list[dict[str, Any]] = []
        if manifest.kind == "playwright":
            visual_mp4 = tmp_path / "visual.mp4"
            if manifest.pw_spec is not None:
                trace_zip = _run_playwright_test_video(
                    manifest,
                    output_path=visual_mp4,
                    work_dir=tmp_path,
                )
                timeline = _build_spec_mode_timeline(
                    manifest=manifest,
                    trace_zip=trace_zip,
                    stderr=stderr,
                )
            else:
                _drive_playwright(
                    manifest,
                    output_path=visual_mp4,
                    work_dir=tmp_path,
                    stderr=stderr,
                    timeline_path=timeline_path,
                )
                if timeline_path.exists():
                    try:
                        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        timeline = []
        elif manifest.kind == "cli":
            visual_mp4 = tmp_path / "visual.mp4"
            _render_cli_vhs(manifest, visual_mp4)
        else:
            raise ManifestError(f"unsupported demonstration.kind: '{manifest.kind}'")

        # The narration pipeline has exactly ONE path when there is a
        # say-timeline: audio-driven Whisper alignment with a vision-LLM
        # keyframe slideshow.
        #
        #   1. Synthesise ALL ``say`` lines as one continuous TTS pass.
        #   2. Whisper word-level timestamps tell us when each line starts
        #      and ends inside that single MP3.
        #   3. Sample candidate frames from the source recording and ask
        #      a vision LLM to pick the BEST candidate per narration step
        #      (the frame whose visible state matches what the line says).
        #   4. Build a slideshow MP4: each chosen still held for its
        #      Whisper-aligned duration. Audio is the master clock.
        #   5. The single MP3 is muxed under the slideshow as the LAST
        #      step (no audio splicing, mixing, or re-timing).
        #
        # When there is no say-timeline (CLI / VHS modes, action-list with
        # no captions), we fall back to a single-clip ``intent`` narration
        # over a uniformly slowed-down visual.
        audio_driven = bool(timeline) and any(e.get("say") for e in timeline)

        narration: NarrationResult | None = None
        retime_factor = manifest.playback_speed_factor
        if audio_driven and not no_narration:
            visual_synced, narration, target_timeline = (
                _align_visual_to_narration(
                    source_visual=visual_mp4,
                    raw_timeline=timeline,
                    work_dir=tmp_path,
                    width=width,
                    height=height,
                )
            )
            timeline = target_timeline
            visual_mp4 = visual_synced
            retime_factor = 1.0

        if abs(retime_factor - 1.0) > 1e-6:
            visual_retimed = tmp_path / "visual_retimed.mp4"
            _retime_video(
                visual_mp4,
                visual_retimed,
                speed_factor=retime_factor,
            )
            visual_mp4 = visual_retimed

        timed_captions = bool(timeline) and any(
            entry.get("say") for entry in timeline
        )
        visual_captioned = tmp_path / "visual_captioned.mp4"
        if timed_captions:
            _burn_timed_captions(
                visual_mp4,
                visual_captioned,
                timeline,
                speed_factor=retime_factor,
                work_dir=tmp_path,
            )
        else:
            _burn_assertion_captions(
                visual_mp4,
                visual_captioned,
                list(manifest.assertions_to_surface),
                work_dir=tmp_path,
            )

        if not no_narration and narration is None:
            narration = _generate_narration(manifest.intent, tmp_path)

        # Freeze-extend the visual when (rare) the audio runs longer than
        # the captioned video — a safety net for the intent-only path,
        # since the audio-driven path already sized the video to the audio.
        if narration is not None:
            visual_sec = _probe_video_duration_sec(visual_captioned) or 0.0
            narration_sec = (narration.ms or 0) / 1000.0
            if narration_sec > visual_sec + 0.01:
                visual_extended = tmp_path / "visual_extended.mp4"
                _extend_video_with_freeze(
                    visual_captioned,
                    visual_extended,
                    target_seconds=narration_sec,
                )
                visual_captioned = visual_extended

        if narration is not None:
            _mux_audio_padded(visual_captioned, narration.audio_path, rendered_mp4)
        else:
            shutil.move(str(visual_captioned), str(rendered_mp4))

        # `duration_seconds` is a cap on the *recorded* timeline; slowdown
        # extends the final clip proportionally (factor 0.5 → 2x final length).
        max_seconds = float(manifest.duration_seconds) / max(
            manifest.playback_speed_factor, 1e-6
        )
        _trim_video_head(rendered_mp4, max_seconds=max_seconds)

        _extract_poster(rendered_mp4, poster_png)

    fragment_txt.write_text(manifest.fragment_id, encoding="utf-8")

    snapshot = _manifest_snapshot(
        manifest,
        narration=narration,
        timeline=timeline,
    )
    manifest_json.write_text(
        json.dumps(snapshot, indent=2) + "\n",
        encoding="utf-8",
    )

    cache_status_txt.write_text("miss\n", encoding="utf-8")

    if cache_dir is not None:
        _cache_store(cache_dir, cache_key, output_dir)

    return RenderResult(
        output_dir=output_dir,
        cache_status="miss",
        manifest=manifest,
        narration=narration,
    )


def _manifest_snapshot(
    manifest: Manifest,
    *,
    narration: NarrationResult | None,
    timeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actions_snapshot: list[dict[str, Any]] = [
        {"kind": a.kind, "say": a.say, "params": a.params}
        for a in manifest.actions
    ]
    return {
        "identifier": manifest.identifier,
        "intent": manifest.intent,
        "fragment_id": manifest.fragment_id,
        "cache_key": manifest.cache_key,
        "duration_seconds": manifest.duration_seconds,
        "resolution": manifest.resolution,
        "playback_speed_factor": manifest.playback_speed_factor,
        "assertions_to_surface": list(manifest.assertions_to_surface),
        "actions": actions_snapshot,
        "timeline": list(timeline) if timeline else [],
        "narration": (
            None
            if narration is None
            else {
                "voice": narration.voice,
                "model": narration.model,
                "ms": narration.ms,
            }
        ),
    }


def _stage_fixtures(
    manifest: Manifest,
    work_dir: Path,
    *,
    stderr,
) -> None:
    if not manifest.fixtures:
        return
    for fixture in manifest.fixtures:
        src_candidates: list[Path] = []
        p = Path(fixture)
        if p.is_absolute():
            src_candidates.append(p)
        else:
            if manifest.source_path is not None:
                src_candidates.append((manifest.source_path.parent / p).resolve())
            src_candidates.append(Path.cwd() / p)
        src = next((c for c in src_candidates if c.exists()), None)
        if src is None:
            print(
                f"[demo-function] fixture not found, skipping: {fixture}",
                file=stderr,
            )
            continue
        dst = work_dir / "fixtures" / Path(fixture).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _drive_playwright(
    manifest: Manifest,
    *,
    output_path: Path,
    work_dir: Path,
    stderr,
    timeline_path: Path | None = None,
) -> None:
    """Drive declarative actions via Playwright sync_api (Python).

    When ``timeline_path`` is provided, writes a JSON list of per-action
    ``{kind, say, t_start_ms, t_end_ms}`` entries timed against the recorded
    video clock (``t=0`` at ``page.goto`` / first action). Used by the
    renderer to place per-action TTS clips and captions at the moments they
    happened instead of spreading them evenly.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ToolingMissingError(
            "playwright is not installed",
            install_hint="pip install playwright && playwright install chromium",
        ) from exc

    width, height = manifest.viewport
    raw_video = work_dir / "video"
    raw_video.mkdir(parents=True, exist_ok=True)

    timeline: list[dict[str, Any]] = []
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=True)
            except Exception as exc:
                raise ToolingMissingError(
                    f"failed to launch Chromium: {exc}",
                    install_hint="playwright install chromium",
                ) from exc
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=str(raw_video),
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()
            captured_video: Path | None = None
            try:
                clock_start = time.monotonic()
                if manifest.url:
                    page.goto(manifest.url, wait_until="networkidle")
                _execute_actions(
                    page,
                    manifest.actions,
                    timeline=timeline,
                    clock_start=clock_start,
                )
            finally:
                if page.video is not None:
                    try:
                        captured_video = Path(page.video.path())
                    except Exception:
                        captured_video = None
                with contextlib.suppress(Exception):
                    context.close()
                with contextlib.suppress(Exception):
                    browser.close()
    except ToolingMissingError:
        raise

    if captured_video is None or not captured_video.exists():
        # Fallback: pick whatever video file was written.
        candidates = sorted(raw_video.glob("*"))
        candidates = [c for c in candidates if c.is_file()]
        if not candidates:
            raise RuntimeError("Playwright produced no video file")
        captured_video = candidates[0]

    _transcode_to_mp4(captured_video, output_path, width=width, height=height)

    if timeline_path is not None:
        timeline_path.write_text(
            json.dumps(timeline, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _build_spec_mode_timeline(
    *,
    manifest: Manifest,
    trace_zip: Path | None,
    stderr,
) -> list[dict[str, Any]]:
    """Zip ``manifest.pw_narration_steps`` onto real ``trace.zip`` timestamps.

    Returns ``[]`` when no narration steps are declared, when the trace is
    missing/empty, or when zero user-visible actions were recorded — in those
    cases the orchestrator falls back to single-clip ``intent`` narration.
    A length mismatch between narration steps and trace actions is logged on
    ``stderr`` and the timeline is truncated to the shorter of the two.
    """
    steps = manifest.pw_narration_steps
    if not steps:
        return []
    if trace_zip is None or not trace_zip.is_file():
        if stderr is not None:
            stderr.write(
                "demo-function: spec-mode narration_steps present but no trace.zip "
                "produced; falling back to single-clip narration.\n"
            )
        return []

    from docgen.pf_trace import build_timeline, parse_trace_zip

    actions = parse_trace_zip(trace_zip)
    if not actions:
        if stderr is not None:
            stderr.write(
                "demo-function: trace.zip contained no user-visible actions; "
                "falling back to single-clip narration.\n"
            )
        return []
    if len(actions) != len(steps) and stderr is not None:
        stderr.write(
            f"demo-function: narration_steps count ({len(steps)}) differs from "
            f"trace actions ({len(actions)}); aligning by index up to "
            f"{min(len(steps), len(actions))}.\n"
        )
    return build_timeline(actions, steps)


_PLAYWRIGHT_OVERRIDE_CONFIG_NAME = "playwright.docgen-override.config.ts"
# Per-action delay applied via Playwright ``launchOptions.slowMo``. Beyond
# making typing/clicks visible at native playback speed, slowMo serves a
# second purpose: Playwright's screencast service has a ~200ms warmup before
# the first frame lands in the WebM. Without slowMo, the first 1-2 user
# actions fire before the recorder is ready and end up off-camera — leaving
# narration lines for actions that the viewer never sees performed. A 500ms
# pre-action delay is generous enough to push every action past the recorder
# warmup and to let interactions read naturally on screen.
_DEFAULT_PLAYWRIGHT_SLOWMO_MS = 500


def _kill_process_group(proc: subprocess.Popen[Any]) -> None:
    """SIGKILL the whole process group of ``proc`` and reap the leader.

    We spawn ``npx playwright`` with ``start_new_session=True`` so its grand-
    children (vite/next/etc. spawned via ``webServer``) live in the same
    process group; killing the group ensures the dev server can't outlive the
    test and keep file descriptors / sockets / ports alive.
    """
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)


def _tail_log(path: Path, *, max_bytes: int = 3000) -> str:
    """Read the last ``max_bytes`` of a log file as text (best-effort)."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _write_playwright_override_config(
    *,
    project_dir: Path,
    output_dir: Path,
    width: int,
    height: int,
    base_url: str | None,
    web_server_command: str | None,
    web_server_url: str | None,
    slow_mo_ms: int = _DEFAULT_PLAYWRIGHT_SLOWMO_MS,
) -> Path:
    """Write a temporary Playwright config in ``project_dir`` that forces
    ``video: on``, ``trace: on``, the docgen viewport, and a ``slowMo`` delay
    so each action is visible on screen, while reusing the project's own
    ``webServer`` declaration when one was discovered.

    The override is placed alongside the user's ``playwright.config.*`` so
    ``testDir: '.'`` and Node module resolution behave identically. Caller is
    responsible for deleting it (try/finally).
    """
    cfg_lines: list[str] = [
        "// AUTO-GENERATED by docgen — safe to delete; recreated per render.",
        'import { defineConfig, devices } from "@playwright/test";',
        "",
        "export default defineConfig({",
        '  testDir: ".",',
        "  fullyParallel: false,",
        "  retries: 0,",
        '  reporter: "line",',
        f"  outputDir: {json.dumps(str(output_dir))},",
        "  use: {",
        '    ...devices["Desktop Chrome"],',
    ]
    if base_url:
        cfg_lines.append(f"    baseURL: {json.dumps(base_url)},")
    cfg_lines.extend(
        [
            f"    viewport: {{ width: {int(width)}, height: {int(height)} }},",
            '    video: "on",',
            '    trace: "on",',
            f"    launchOptions: {{ slowMo: {int(slow_mo_ms)} }},",
            "  },",
        ]
    )
    if web_server_command and web_server_url:
        cfg_lines.extend(
            [
                "  webServer: {",
                f"    command: {json.dumps(web_server_command)},",
                f"    url: {json.dumps(web_server_url)},",
                "    reuseExistingServer: true,",
                "    timeout: 120000,",
                "  },",
            ]
        )
    cfg_lines.append("});")
    cfg_lines.append("")

    path = project_dir / _PLAYWRIGHT_OVERRIDE_CONFIG_NAME
    path.write_text("\n".join(cfg_lines), encoding="utf-8")
    return path


def _run_playwright_test_video(
    manifest: Manifest,
    *,
    output_path: Path,
    work_dir: Path,
) -> Path | None:
    """Run ``npx playwright test`` on a spec with ``--grep`` and capture WebM → MP4.

    Returns the absolute path to the run's ``trace.zip`` when one was produced
    (``--trace=on``), else ``None``. The trace is the source of truth for
    per-step recording timestamps used by ``narration_steps`` syncing.

    Implementation notes:

    * Playwright 1.49+ removed ``--video``, ``--viewport-size``, and
      ``--output-dir`` from the CLI surface; they must be set in the config's
      ``use:`` block. We therefore generate a transient
      ``playwright.docgen-override.config.ts`` next to the user's own config
      that pins ``video: on``, ``trace: on``, the manifest viewport, the
      base URL, and (when discovered) the user's ``webServer`` declaration.
      The override is removed in a ``finally`` after the run.
    * ``cwd`` is set to the project dir so Node module resolution finds
      ``@playwright/test`` from the project's ``node_modules``.
    """
    if manifest.pw_spec is None or not manifest.pw_grep:
        raise ManifestError("internal: spec/grep required for Playwright test mode")

    if shutil.which("npx") is None:
        raise ToolingMissingError(
            "npx not found on PATH (needed for Playwright test recording)",
            install_hint="Install Node.js so `npx` is available.",
        )

    spec = manifest.pw_spec.resolve()
    if not spec.exists():
        raise ManifestError(f"demonstration.spec not found: {spec}")

    out_pw = work_dir / "playwright-output"
    out_pw.mkdir(parents=True, exist_ok=True)
    width, height = manifest.viewport
    timeout_ms = min(max(manifest.duration_seconds, 5) * 1000 + 10_000, 120_000)

    project_dir = (manifest.pw_cwd or spec.parent).resolve()

    from docgen.test_discovery import (
        find_playwright_config,
        parse_playwright_config_insights,
    )

    cfg_insights: dict[str, Any] = {}
    user_cfg = find_playwright_config(project_dir)
    if user_cfg is not None:
        cfg_insights = parse_playwright_config_insights(user_cfg)
    base_url = manifest.pw_base_url or cfg_insights.get("base_url")

    override_cfg = _write_playwright_override_config(
        project_dir=project_dir,
        output_dir=out_pw,
        width=width,
        height=height,
        base_url=base_url,
        web_server_command=cfg_insights.get("web_server_command"),
        web_server_url=cfg_insights.get("web_server_url"),
    )

    proc: subprocess.Popen[bytes] | None = None
    try:
        cmd: list[str] = [
            "npx",
            "playwright",
            "test",
            str(spec),
            "-g",
            manifest.pw_grep,
            f"--config={override_cfg}",
            f"--timeout={int(timeout_ms)}",
            "--trace=on",
            f"--output={out_pw}",
            "--reporter=line",
        ]

        # We CANNOT use ``capture_output=True`` here. Playwright's
        # ``webServer`` block spawns the project's dev server (e.g. vite) as a
        # grandchild that inherits our stdout/stderr pipes. Even after the
        # test itself finishes and writes ``trace.zip`` / ``video.webm``, the
        # dev server keeps those file descriptors open, so ``communicate()``
        # would block forever waiting for EOF. Redirect to log files instead
        # (file descriptors don't keep us blocked) and spawn the whole tree
        # in a fresh process group so we can SIGKILL it cleanly in finally.
        stdout_log = work_dir / "playwright.stdout.log"
        stderr_log = work_dir / "playwright.stderr.log"
        timeout_sec = max(60, int(timeout_ms / 1000) + 30)
        with stdout_log.open("wb") as out_f, stderr_log.open("wb") as err_f:
            proc = subprocess.Popen(
                cmd,
                cwd=str(project_dir),
                stdout=out_f,
                stderr=err_f,
                start_new_session=True,
            )
            try:
                rc = proc.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                _kill_process_group(proc)
                raise RuntimeError(
                    f"playwright test timed out after {timeout_sec}s "
                    f"(stdout tail: {_tail_log(stdout_log)})"
                )

        if rc != 0:
            tail = (
                _tail_log(stderr_log) + "\n" + _tail_log(stdout_log)
            ).strip()
            raise RuntimeError(
                f"playwright test failed (exit {rc}):\n{tail[-3_000:]}"
            )

        webms = sorted(out_pw.rglob("*.webm"))
        if not webms:
            raise RuntimeError(
                f"playwright test produced no .webm under {out_pw}"
            )
        raw_video = max(webms, key=lambda p: p.stat().st_size)

        _transcode_to_mp4(raw_video, output_path, width=width, height=height)

        from docgen.pf_trace import find_trace_zip

        return find_trace_zip(out_pw)
    finally:
        # Always kill the entire process group — Playwright's ``webServer``
        # (vite, next dev, etc.) is a grandchild and won't die just because
        # the npx wrapper got SIGTERM. We don't care if everything already
        # exited cleanly; SIGKILL on a dead group is a no-op.
        if proc is not None:
            _kill_process_group(proc)
        try:
            override_cfg.unlink()
        except OSError:
            pass


def _render_cli_vhs(
    manifest: Manifest,
    output_path: Path,
) -> None:
    """Render a VHS tape via ``VHSRunner`` and normalize to the manifest viewport MP4."""
    from docgen.vhs import VHSRunner

    tape = manifest.cli_tape
    if tape is None:
        raise ManifestError("internal: cli_tape required for kind cli")

    cfg_base = manifest.source_path.parent if manifest.source_path else tape.parent
    cfg = Config.minimal(cfg_base)
    runner = VHSRunner(cfg)
    result = runner.render_tape_at(tape, strict=False)
    if not result.success:
        detail = "; ".join(result.errors) if result.errors else "unknown error"
        raise RuntimeError(f"VHS tape render failed: {detail}")

    text = tape.read_text(encoding="utf-8")
    rel_out: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("output "):
            rest = stripped.split(None, 1)
            if len(rest) > 1:
                rel_out = rest[1].strip().strip('"').strip("'")
            break
    if not rel_out:
        raise ManifestError(
            f"VHS tape must contain an `Output ...` line (found none in {tape.name})"
        )

    produced = (tape.parent / rel_out).resolve()
    if not produced.exists():
        raise RuntimeError(f"VHS did not produce expected file: {produced}")

    width, height = manifest.viewport
    _transcode_to_mp4(produced, output_path, width=width, height=height)


def _execute_actions(
    page: Any,
    actions: Iterable[Action],
    *,
    timeline: list[dict[str, Any]] | None = None,
    clock_start: float | None = None,
) -> None:
    """Run `actions` against a live Playwright `page`.

    When ``timeline`` and ``clock_start`` are provided, appends one entry per
    action with the wall-clock millisecond span (relative to ``clock_start``)
    so the renderer can place per-action TTS clips and captions at the
    moments the actions happened.
    """
    for action in actions:
        t_start_ms = (
            int(round((time.monotonic() - clock_start) * 1000))
            if (timeline is not None and clock_start is not None)
            else 0
        )
        p = action.params
        if action.kind == "goto":
            page.goto(p.get("url", ""), wait_until="networkidle")
        elif action.kind == "click":
            page.click(p["selector"])
        elif action.kind == "fill":
            page.fill(p["selector"], p["value"])
        elif action.kind == "type":
            page.click(p["selector"])
            page.keyboard.type(p["value"], delay=int(p.get("delay_ms", 40)))
        elif action.kind == "wait_for":
            page.wait_for_selector(p["selector"], timeout=int(p.get("timeout_ms", 10000)))
        elif action.kind == "wait_for_text":
            page.locator(p["selector"]).filter(has_text=p["text"]).first.wait_for(
                state="visible",
                timeout=int(p.get("timeout_ms", 10000)),
            )
        elif action.kind == "wait":
            page.wait_for_timeout(int(p["ms"]))
        elif action.kind == "screenshot":
            page.screenshot(path=str(p["path"]))
        else:
            raise ManifestError(f"unsupported action kind: '{action.kind}'")
        if timeline is not None and clock_start is not None:
            t_end_ms = int(round((time.monotonic() - clock_start) * 1000))
            timeline.append(
                {
                    "kind": action.kind,
                    "say": action.say,
                    "t_start_ms": t_start_ms,
                    "t_end_ms": t_end_ms,
                }
            )


# ---------------------------------------------------------------------------
# CLI entry point (called from docgen.cli:demo_function)
# ---------------------------------------------------------------------------


def run_cli(
    manifest_arg: str,
    output_dir_arg: str,
    *,
    grep: str | None = None,
    cache_dir_arg: str | None = None,
    no_narration: bool = False,
    stderr=None,
    stdout=None,
) -> int:
    """Execute the `docgen demo-function` flow and return an exit code.

    Lives here (not in cli.py) to keep the runner testable without touching
    Click's machinery.
    """
    if stderr is None:
        stderr = sys.stderr
    if stdout is None:
        stdout = sys.stdout

    try:
        manifest = load_manifest(manifest_arg, grep=grep)
    except FileNotFoundError as exc:
        print(f"[demo-function] {exc}", file=stderr)
        return EXIT_INVALID
    except ManifestError as exc:
        print(f"[demo-function] {exc}", file=stderr)
        return EXIT_INVALID

    output_dir = Path(output_dir_arg)
    cache_dir = Path(cache_dir_arg) if cache_dir_arg else None

    try:
        result = render(
            manifest,
            output_dir,
            cache_dir=cache_dir,
            no_narration=no_narration,
            stderr=stderr,
        )
    except PlaceholderManifest as exc:
        print(f"[demo-function] neutral skip: {exc}", file=stderr)
        return EXIT_NEUTRAL_SKIP
    except ToolingMissingError as exc:
        print(f"[demo-function] {exc}", file=stderr)
        print(f"  install: {exc.install_hint}", file=stderr)
        return EXIT_TOOLING_MISSING
    except (ManifestError, RuntimeError) as exc:
        print(f"[demo-function] render failed: {exc}", file=stderr)
        return EXIT_INVALID

    print(
        f"[demo-function] {result.cache_status}: "
        f"{manifest.fragment_id} -> {result.output_dir}",
        file=stdout,
    )
    return EXIT_OK


__all__ = [
    "Action",
    "Manifest",
    "ManifestError",
    "PlaceholderManifest",
    "ToolingMissingError",
    "RenderResult",
    "NarrationResult",
    "load_manifest",
    "manifest_from_mapping",
    "render",
    "run_cli",
    "generate_capture_script",
    "EXIT_OK",
    "EXIT_INVALID",
    "EXIT_TOOLING_MISSING",
    "EXIT_NEUTRAL_SKIP",
    "SUPPORTED_ACTION_KINDS",
    "CACHED_ARTIFACTS",
    "HARD_CAP_SECONDS",
]
