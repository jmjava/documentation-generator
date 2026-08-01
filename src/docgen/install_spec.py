"""Canonical install strings for using docgen as an external tool (not vendored).

Consumers should ``pip install`` (or ``pipx`` / ``uv tool``) this package and keep
only a demo **bundle** (``docgen.yaml``, hints, narration, …) in their repo —
never a copy of the ``documentation-generator`` source tree.
"""

from __future__ import annotations

from importlib import metadata

# Default Git install URL (main tip). Prefer pinning ``@<sha>`` in CI.
DOCGEN_GIT_URL = "git+https://github.com/jmjava/documentation-generator.git"
DOCGEN_PIP_SPEC = f"docgen @ {DOCGEN_GIT_URL}"
DOCGEN_PIP_MANIM_SPEC = f"docgen[manim] @ {DOCGEN_GIT_URL}"


def package_version() -> str:
    """Installed distribution version, or ``unknown`` when not installed as a package."""
    try:
        return metadata.version("docgen")
    except metadata.PackageNotFoundError:
        return "unknown"


def requirements_docgen_txt(*, pin_ref: str | None = None) -> str:
    """Contents of a consumer ``requirements-docgen.txt``.

    ``pin_ref`` is an optional git ref (commit SHA, tag, or branch). When omitted,
    the file installs from the default remote tip and comments show how to pin.
    """
    ref = (pin_ref or "").strip()
    if ref:
        pip_line = f"docgen @ {DOCGEN_GIT_URL}@{ref}"
        manim_line = f'docgen[manim] @ {DOCGEN_GIT_URL}@{ref}'
        pin_note = f"# Pinned ref: {ref}\n"
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
        f"{pin_note}"
        f"{pip_line}\n"
    )
