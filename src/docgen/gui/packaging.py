"""PyInstaller data / hidden-import lists for the desktop GUI freeze.

The frozen binary is a **GUI shell** (wizard + benchmark Vue view). It does
not bundle Manim, ffmpeg, or OpenAI clients as required imports — those stay
optional for the pip CLI.
"""

from __future__ import annotations

from pathlib import Path

from docgen.resources import package_root


def pyinstaller_datas() -> list[tuple[str, str]]:
    """``(src, dest)`` pairs for ``Analysis(datas=...)``."""
    root = package_root()
    pairs: list[tuple[str, str]] = []
    for name in ("templates", "static", "benchmark_data"):
        src = root / name
        if src.is_dir():
            pairs.append((str(src), f"docgen/{name}"))
    return pairs


def pyinstaller_hiddenimports() -> list[str]:
    return [
        "docgen",
        "docgen.cli",
        "docgen.config",
        "docgen.gui",
        "docgen.gui.desktop",
        "docgen.gui.__main__",
        "docgen.resources",
        "docgen.scene_benchmark",
        "docgen.scene_clock_harness",
        "docgen.scene_spec",
        "docgen.scene_asset_validate",
        "docgen.manim_primitives",
        "docgen.wizard",
        "docgen.install_spec",
        "flask",
        "jinja2",
        "click",
        "yaml",
        "webview",
    ]


def spec_path() -> Path:
    """Repo-root ``packaging/docgen-gui.spec`` when running from a checkout."""
    here = Path(__file__).resolve()
    # src/docgen/gui/packaging.py → repo root
    root = here.parents[3]
    return root / "packaging" / "docgen-gui.spec"
