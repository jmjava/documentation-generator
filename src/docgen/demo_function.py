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
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from docgen.config import Config

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
    the YAML mapping for the action (selector, value, ms, etc.).
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)

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
        params = {k: v for k, v in raw.items() if k != "kind"}
        return cls(kind=kind, params=params)


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
    source_path: Path | None = None
    # File whose bytes define the demo "function" for caching (spec, tape, or manifest).
    fn_source_path: Path | None = None
    # Playwright test recording (npx @playwright/test). When set, `actions` / `url` are unused.
    pw_spec: Path | None = None
    pw_grep: str | None = None
    pw_cwd: Path | None = None
    pw_base_url: str | None = None
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
        h = hashlib.sha256()
        h.update(fn_src.encode("ascii"))
        h.update(b"\x00")
        h.update(intent_sha.encode("ascii"))
        h.update(b"\x00")
        h.update(fixture_sha.encode("ascii"))
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
        source_path=source_path,
        fn_source_path=fn_source_path,
        pw_spec=pw_spec,
        pw_grep=pw_grep,
        pw_cwd=pw_cwd,
        pw_base_url=pw_base_url,
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


def _burn_assertion_captions(
    video_in: Path,
    video_out: Path,
    assertions: list[str],
    *,
    work_dir: Path,
) -> None:
    """Overlay `assertions` as bottom subtitles (WebVTT via ffmpeg)."""
    if not assertions:
        shutil.copy2(video_in, video_out)
        return
    _ensure_ffmpeg()
    dur = _probe_video_duration_sec(video_in) or 30.0
    vtt_path = work_dir / "assertions.vtt"
    vtt_path.write_text(
        _vtt_from_assertions(assertions, total_sec=dur),
        encoding="utf-8",
    )
    # Escape for ffmpeg filtergraph: colons, backslashes
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
            f"ffmpeg assertion burn-in failed: {proc.stderr[-500:]}"
        )


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


def _generate_narration(
    intent: str,
    work_dir: Path,
    *,
    voice: str = "coral",
    model: str = "gpt-4o-mini-tts",
) -> NarrationResult:
    """Generate narration MP3 from `intent` using the OpenAI TTS path.

    Mirrors `docgen.tts.TTSGenerator` but is self-contained — demo-function
    runs are one-shot and don't need the segment-aware machinery.
    """
    import openai

    out = work_dir / "narration.mp3"
    client = openai.OpenAI()
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=intent,
        instructions=(
            "You are narrating a per-function code demo. Speak in a calm, "
            "professional tone. One sentence."
        ),
    )
    response.stream_to_file(str(out))
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

    with tempfile.TemporaryDirectory(prefix="docgen-demo-") as tmp:
        tmp_path = Path(tmp)
        _stage_fixtures(manifest, tmp_path, stderr=stderr)

        if manifest.kind == "playwright":
            visual_mp4 = tmp_path / "visual.mp4"
            if manifest.pw_spec is not None:
                _run_playwright_test_video(
                    manifest,
                    output_path=visual_mp4,
                    work_dir=tmp_path,
                )
            else:
                _drive_playwright(
                    manifest,
                    output_path=visual_mp4,
                    work_dir=tmp_path,
                    stderr=stderr,
                )
        elif manifest.kind == "cli":
            visual_mp4 = tmp_path / "visual.mp4"
            _render_cli_vhs(manifest, visual_mp4)
        else:
            raise ManifestError(f"unsupported demonstration.kind: '{manifest.kind}'")

        visual_captioned = tmp_path / "visual_captioned.mp4"
        _burn_assertion_captions(
            visual_mp4,
            visual_captioned,
            list(manifest.assertions_to_surface),
            work_dir=tmp_path,
        )

        narration: NarrationResult | None = None
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if no_narration:
            pass
        elif not api_key:
            print(
                "[demo-function] OPENAI_API_KEY not set; emitting visual-only "
                "video. Pass --no-narration to silence this warning.",
                file=stderr,
            )
        else:
            try:
                narration = _generate_narration(manifest.intent, tmp_path)
            except Exception as exc:  # pragma: no cover - network-dependent
                print(
                    f"[demo-function] narration failed ({exc}); "
                    "emitting visual-only video.",
                    file=stderr,
                )
                narration = None

        if narration is not None:
            _mux_audio(visual_captioned, narration.audio_path, rendered_mp4)
        else:
            shutil.move(str(visual_captioned), str(rendered_mp4))

        _trim_video_head(
            rendered_mp4,
            max_seconds=float(manifest.duration_seconds),
        )

        _extract_poster(rendered_mp4, poster_png)

    fragment_txt.write_text(manifest.fragment_id, encoding="utf-8")

    snapshot = _manifest_snapshot(manifest, narration=narration)
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
) -> dict[str, Any]:
    return {
        "identifier": manifest.identifier,
        "intent": manifest.intent,
        "fragment_id": manifest.fragment_id,
        "cache_key": manifest.cache_key,
        "duration_seconds": manifest.duration_seconds,
        "resolution": manifest.resolution,
        "assertions_to_surface": list(manifest.assertions_to_surface),
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
) -> None:
    """Drive declarative actions via Playwright sync_api (Python)."""
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
                if manifest.url:
                    page.goto(manifest.url, wait_until="networkidle")
                _execute_actions(page, manifest.actions)
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


def _run_playwright_test_video(
    manifest: Manifest,
    *,
    output_path: Path,
    work_dir: Path,
) -> None:
    """Run ``npx playwright test`` on a spec with ``--grep`` and capture WebM → MP4."""
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

    cmd: list[str] = [
        "npx",
        "playwright",
        "test",
        str(spec),
        "-g",
        manifest.pw_grep,
        f"--timeout={int(timeout_ms)}",
        "--video=on",
        f"--viewport-size={width},{height}",
        f"--output-dir={out_pw}",
        "--reporter=line",
    ]
    if manifest.pw_base_url:
        cmd.append(f"--base-url={manifest.pw_base_url}")

    cwd = (manifest.pw_cwd or spec.parent).resolve()

    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=max(60, int(timeout_ms / 1000) + 30),
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-800:]
        raise RuntimeError(
            f"playwright test failed (exit {proc.returncode}): {tail}"
        )

    webms = sorted(out_pw.rglob("*.webm"))
    if not webms:
        raise RuntimeError(
            f"playwright test produced no .webm under {out_pw}"
        )
    raw_video = max(webms, key=lambda p: p.stat().st_size)

    _transcode_to_mp4(raw_video, output_path, width=width, height=height)


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


def _execute_actions(page: Any, actions: Iterable[Action]) -> None:
    """Run `actions` against a live Playwright `page`. Mirrors `_render_action`."""
    for action in actions:
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
