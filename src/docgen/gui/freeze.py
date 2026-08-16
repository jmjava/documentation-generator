"""Build and smoke-test the desktop GUI freeze (not the full Manim CLI)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from docgen.gui.packaging import pyinstaller_datas, pyinstaller_hiddenimports, spec_path

GUI_NAME = "docgen-gui"
_EXCLUDES = ("manim", "cv2", "torch", "IPython")


def gui_entry_script() -> Path:
    import docgen.gui.__main__ as entry

    return Path(entry.__file__).resolve()


def frozen_binary(distpath: Path) -> Path:
    """Onedir binary: ``dist/docgen-gui/docgen-gui`` (``.exe`` on Windows)."""
    folder = Path(distpath) / GUI_NAME
    win = folder / f"{GUI_NAME}.exe"
    if win.is_file():
        return win
    return folder / GUI_NAME


def _pyinstaller_run(args: list[str]) -> None:
    try:
        from PyInstaller.__main__ import run as pyi_run
    except ImportError as exc:
        raise RuntimeError(
            "PyInstaller is not installed. pip install 'docgen[packaging]'"
        ) from exc
    pyi_run(args)


def run_freeze(
    *,
    distpath: Path,
    workpath: Path | None = None,
    noconfirm: bool = True,
) -> Path:
    """Run PyInstaller and return the onedir binary path."""
    distpath = Path(distpath)
    distpath.mkdir(parents=True, exist_ok=True)
    spec = spec_path()
    if spec.is_file():
        args = ["--distpath", str(distpath)]
        if noconfirm:
            args.append("--noconfirm")
        if workpath is not None:
            args.extend(["--workpath", str(workpath)])
        args.append(str(spec))
        _pyinstaller_run(args)
    else:
        args = [
            "--onedir",
            "--noconsole",
            "--name",
            GUI_NAME,
            "--distpath",
            str(distpath),
        ]
        if noconfirm:
            args.append("--noconfirm")
        if workpath is not None:
            args.extend(["--workpath", str(workpath)])
        sep = ";" if os.name == "nt" else ":"
        for src, dest in pyinstaller_datas():
            args.extend(["--add-data", f"{src}{sep}{dest}"])
        for name in pyinstaller_hiddenimports():
            args.extend(["--hidden-import", name])
        for mod in _EXCLUDES:
            args.extend(["--exclude-module", mod])
        args.append(str(gui_entry_script()))
        _pyinstaller_run(args)
    binary = frozen_binary(distpath)
    if not binary.is_file():
        raise RuntimeError(f"freeze produced no binary at {binary}")
    return binary


def smoke_session(
    config: Any | None = None,
    *,
    output: Path | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    """Start the local Flask GUI and GET ``/``, ``/api/session``, ``/api/benchmark``."""
    from docgen.gui.desktop import serve_url

    url, httpd = serve_url(config, path="/?view=benchmark")
    try:
        base = url.split("?", 1)[0].rstrip("/")
        with urlopen(base + "/", timeout=timeout) as page:
            html = page.read()
            page_status = page.status
        with urlopen(base + "/api/session", timeout=timeout) as resp:
            session = json.loads(resp.read().decode("utf-8"))
        with urlopen(base + "/api/benchmark?case=early_title", timeout=timeout) as resp:
            report = json.loads(resp.read().decode("utf-8"))
        result: dict[str, Any] = {
            "ok": page_status == 200
            and report.get("ok") is True
            and session.get("pipeline_available") is not None,
            "url": url,
            "session": session,
            "case_id": (report.get("cases") or [{}])[0].get("case_id"),
            "html_has_benchmark": b"benchmark-app" in html,
            "meets_baseline": report.get("meets_baseline"),
        }
        if not result["html_has_benchmark"]:
            result["ok"] = False
    finally:
        httpd.shutdown()
    if output is not None:
        Path(output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not result["ok"]:
        raise RuntimeError(f"gui smoke failed: {result}")
    return result


def smoke_frozen_binary(
    binary: Path,
    *,
    output: Path,
    timeout: float = 180,
) -> dict[str, Any]:
    """Run ``docgen-gui --smoke`` and read the JSON report."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(binary), "--smoke", "--smoke-output", str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"frozen smoke exited {proc.returncode}: {err or 'no output'}"
        )
    if not output.is_file():
        raise RuntimeError(f"frozen smoke wrote no report at {output}")
    return json.loads(output.read_text(encoding="utf-8"))


def smoke_current(*, output: Path | None = None, config: Any | None = None) -> dict[str, Any]:
    """Smoke this interpreter (editable install or frozen ``sys.executable``)."""
    if getattr(sys, "frozen", False):
        return smoke_session(config, output=output)
    return smoke_session(config, output=output)
