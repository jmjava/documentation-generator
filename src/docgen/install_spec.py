"""Canonical install strings for using docgen as an external tool (not vendored).

Consumers should ``pip install`` (or ``pipx`` / ``uv tool``) this package and keep
only a demo **bundle** (``docgen.yaml``, hints, narration, …) in their repo —
never a copy of the ``documentation-generator`` source tree.

The wizard can call :func:`update_docgen_install` to upgrade the running
environment and optionally rewrite ``requirements-docgen.txt``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

# Default Git install URL (main tip). Prefer pinning ``@<sha>`` in CI.
DOCGEN_GIT_URL = "git+https://github.com/jmjava/documentation-generator.git"
DOCGEN_PIP_SPEC = f"docgen @ {DOCGEN_GIT_URL}"
DOCGEN_PIP_MANIM_SPEC = f"docgen[manim] @ {DOCGEN_GIT_URL}"

# Safe git refs only (SHA, tag, branch). Blocks shell metacharacters.
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
_PIN_LINE_RE = re.compile(
    r"^\s*docgen(?:\[[^\]]+\])?\s*@\s*"
    r"git\+https://github\.com/jmjava/documentation-generator\.git"
    r"(?:@(?P<ref>[A-Za-z0-9._/-]+))?\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ToolInfo:
    version: str
    location: str | None
    editable: bool
    pip_spec: str
    requirements_path: str | None
    requirements_pin: str | None
    python: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    ref: str
    pip_spec: str
    version_before: str
    version_after: str
    requirements_updated: bool
    requirements_path: str | None
    log: str
    restart_required: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def package_version() -> str:
    """Installed distribution version, or ``unknown`` when not installed as a package."""
    try:
        return metadata.version("docgen")
    except metadata.PackageNotFoundError:
        return "unknown"


def validate_git_ref(ref: str) -> str:
    """Return a sanitized git ref or raise ``ValueError``."""
    cleaned = (ref or "").strip() or "main"
    if cleaned.startswith("@"):
        cleaned = cleaned[1:]
    if not _REF_RE.match(cleaned):
        raise ValueError(
            f"invalid git ref {ref!r}: use a branch, tag, or commit SHA "
            "(letters, digits, . _ / - only)"
        )
    if ".." in cleaned or cleaned.startswith("-"):
        raise ValueError(f"invalid git ref {ref!r}")
    return cleaned


def pip_spec_for_ref(ref: str | None = None, *, with_manim: bool = False) -> str:
    """Build a ``docgen @ git+…`` (or ``docgen[manim] @ …``) requirement string."""
    if ref is None or not str(ref).strip():
        return DOCGEN_PIP_MANIM_SPEC if with_manim else DOCGEN_PIP_SPEC
    safe = validate_git_ref(ref)
    base = f"{DOCGEN_GIT_URL}@{safe}"
    return f"docgen[manim] @ {base}" if with_manim else f"docgen @ {base}"


def requirements_docgen_txt(*, pin_ref: str | None = None) -> str:
    """Contents of a consumer ``requirements-docgen.txt``.

    ``pin_ref`` is an optional git ref (commit SHA, tag, or branch). When omitted,
    the file installs from the default remote tip and comments show how to pin.
    """
    ref = (pin_ref or "").strip()
    if ref:
        safe = validate_git_ref(ref)
        pip_line = pip_spec_for_ref(safe, with_manim=False)
        manim_line = pip_spec_for_ref(safe, with_manim=True)
        pin_note = f"# Pinned ref: {safe}\n"
    else:
        pip_line = DOCGEN_PIP_SPEC
        manim_line = DOCGEN_PIP_MANIM_SPEC
        pin_note = (
            "# Tip: pin a commit SHA for reproducible CI, e.g.\n"
            f"#   docgen @ {DOCGEN_GIT_URL}@<sha>\n"
        )

    return (
        "# docgen — external CLI/library (do NOT vendor documentation-generator into this repo).\n"
        "#\n"
        "# Install into a project venv:\n"
        "#   python3 -m venv .venv && source .venv/bin/activate\n"
        "#   pip install -r requirements-docgen.txt\n"
        "#\n"
        "# Or isolate with pipx / uv (global `docgen` on PATH, no project src copy):\n"
        f"#   pipx install '{pip_line}'\n"
        f"#   uv tool install '{pip_line}'\n"
        "#\n"
        "# Manim visuals (optional extra):\n"
        f"#   pip install '{manim_line}'\n"
        "#\n"
        "# Wizard: Production → Tool → Update docgen (rewrites this file when pinned).\n"
        "#\n"
        f"{pin_note}"
        f"{pip_line}\n"
    )


def find_requirements_docgen(bundle_dir: Path | None) -> Path | None:
    if bundle_dir is None:
        return None
    path = Path(bundle_dir) / "requirements-docgen.txt"
    return path if path.is_file() else None


def read_requirements_pin(path: Path | None) -> str | None:
    """Return the git ref pinned in ``requirements-docgen.txt``, if any."""
    if path is None or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _PIN_LINE_RE.search(text)
    if not m:
        return None
    return m.group("ref")


def write_requirements_docgen(bundle_dir: Path, *, pin_ref: str | None = None) -> Path:
    """Write/overwrite ``requirements-docgen.txt`` under the bundle."""
    path = Path(bundle_dir) / "requirements-docgen.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(requirements_docgen_txt(pin_ref=pin_ref), encoding="utf-8")
    return path


def _distribution_location() -> tuple[str | None, bool]:
    """Return (install location string, editable)."""
    try:
        dist = metadata.distribution("docgen")
    except metadata.PackageNotFoundError:
        # Running from a source checkout on PYTHONPATH
        here = Path(__file__).resolve().parent
        return str(here), True
    # Prefer direct_url for editable / VCS installs
    try:
        direct = dist.read_text("direct_url.json")
    except Exception:
        direct = None
    if direct and '"editable"' in direct:
        return str(dist.locate_file("")), True
    try:
        loc = str(dist.locate_file(""))
    except Exception:
        loc = None
    return loc, False


def tool_info(bundle_dir: Path | None = None) -> ToolInfo:
    """Snapshot of the installed docgen tool + optional bundle pin."""
    req = find_requirements_docgen(bundle_dir)
    loc, editable = _distribution_location()
    return ToolInfo(
        version=package_version(),
        location=loc,
        editable=editable,
        pip_spec=DOCGEN_PIP_SPEC,
        requirements_path=str(req) if req else None,
        requirements_pin=read_requirements_pin(req),
        python=sys.executable,
    )


def update_docgen_install(
    *,
    ref: str = "main",
    with_manim: bool = False,
    bundle_dir: Path | None = None,
    update_requirements: bool = True,
    timeout_sec: int = 300,
) -> UpdateResult:
    """Upgrade docgen in the current interpreter via ``python -m pip install``.

    Only the canonical ``jmjava/documentation-generator`` git URL is allowed.
    After a successful upgrade the running wizard process still serves the old
    code until restarted (``restart_required=True``).
    """
    safe_ref = validate_git_ref(ref)
    spec = pip_spec_for_ref(safe_ref, with_manim=with_manim)
    before = package_version()
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        spec,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return UpdateResult(
            ok=False,
            ref=safe_ref,
            pip_spec=spec,
            version_before=before,
            version_after=before,
            requirements_updated=False,
            requirements_path=None,
            log="pip install timed out",
            error="timeout",
        )
    except OSError as exc:
        return UpdateResult(
            ok=False,
            ref=safe_ref,
            pip_spec=spec,
            version_before=before,
            version_after=before,
            requirements_updated=False,
            requirements_path=None,
            log=str(exc),
            error=str(exc),
        )

    log = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return UpdateResult(
            ok=False,
            ref=safe_ref,
            pip_spec=spec,
            version_before=before,
            version_after=before,
            requirements_updated=False,
            requirements_path=None,
            log=log or f"pip exited {proc.returncode}",
            error=f"pip exited {proc.returncode}",
        )

    # Invalidate importlib metadata caches so version_after is fresh.
    try:
        metadata.packages_distributions.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    after = package_version()

    req_path: str | None = None
    req_updated = False
    if update_requirements and bundle_dir is not None:
        written = write_requirements_docgen(Path(bundle_dir), pin_ref=safe_ref)
        req_path = str(written)
        req_updated = True

    return UpdateResult(
        ok=True,
        ref=safe_ref,
        pip_spec=spec,
        version_before=before,
        version_after=after,
        requirements_updated=req_updated,
        requirements_path=req_path,
        log=log,
        restart_required=True,
    )
