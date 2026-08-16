# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Vue desktop GUI (not the full Manim CLI).

From the repo root, after ``pip install -e '.[packaging]'``:

    pyinstaller packaging/docgen-gui.spec
"""

import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    env = os.environ.get("DOCGEN_FREEZE_ROOT")
    if env:
        root = Path(env).resolve()
        if (root / "src" / "docgen" / "gui" / "__main__.py").is_file():
            return root
    here = Path(os.path.abspath(str(SPECPATH))).resolve()
    for candidate in (
        here.parent.parent,
        here.parent,
        Path.cwd(),
        Path.cwd().parent,
    ):
        if (candidate / "src" / "docgen" / "gui" / "__main__.py").is_file():
            return candidate
    raise SystemExit(
        f"cannot locate docgen repo root from SPECPATH={SPECPATH!r} cwd={Path.cwd()}"
    )


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "src"))

from docgen.gui.packaging import pyinstaller_datas, pyinstaller_hiddenimports  # noqa: E402

a = Analysis(
    [str(ROOT / "src" / "docgen" / "gui" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=pyinstaller_datas(),
    hiddenimports=pyinstaller_hiddenimports(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["manim", "cv2", "torch", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="docgen-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="docgen-gui",
)
