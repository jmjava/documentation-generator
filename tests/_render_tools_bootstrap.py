"""Download ffmpeg, ffprobe, and VHS into ``tests/.bin-cache`` when demo_function render tests run.

Keeps the default ``pytest`` run self-contained (no ``skipif``) without sudo.
"""

from __future__ import annotations

import os
import platform
import stat
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VHS_RELEASE = "v0.11.0"
VHS_DOWNLOAD_BASE = f"https://github.com/charmbracelet/vhs/releases/download/{VHS_RELEASE}/"
WIN_FFMPEG_ZIP = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
EVERMEET_FFMPEG_ZIP = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
EVERMEET_FFPROBE_ZIP = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"


def bin_cache_root() -> Path:
    return Path(__file__).resolve().parent / ".bin-cache"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "docgen-test-bootstrap/1.0"})
    with urllib.request.urlopen(req, timeout=900) as resp:
        dest.write_bytes(resp.read())


def _prepend_path(dir_path: Path) -> None:
    ps = str(dir_path.resolve())
    cur = os.environ.get("PATH", "")
    parts = cur.split(os.pathsep) if cur else []
    if ps not in parts:
        os.environ["PATH"] = ps + os.pathsep + cur


def _augment_common_path_prefixes() -> None:
    if sys.platform == "darwin":
        for base in ("/opt/homebrew/bin", "/usr/local/bin"):
            p = Path(base)
            if p.is_dir():
                _prepend_path(p)


def _chmod_plus_x(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR)


def _vhs_release_asset() -> tuple[str, bool]:
    """Return (filename, is_zip)."""
    if sys.platform == "win32":
        return "vhs_0.11.0_Windows_x86_64.zip", True
    if sys.platform == "darwin":
        if platform.machine().lower() == "arm64":
            return "vhs_0.11.0_Darwin_arm64.tar.gz", False
        return "vhs_0.11.0_Darwin_x86_64.tar.gz", False
    if sys.platform.startswith("linux"):
        m = platform.machine().lower()
        if m in ("x86_64", "amd64"):
            return "vhs_0.11.0_Linux_x86_64.tar.gz", False
        if m in ("aarch64", "arm64"):
            return "vhs_0.11.0_Linux_arm64.tar.gz", False
    raise OSError(f"Unsupported platform for bundled VHS: {sys.platform} {platform.machine()}")


def ensure_vhs_on_path() -> None:
    import shutil

    if shutil.which("vhs"):
        return
    tdir = bin_cache_root() / "vhs-extract"
    tdir.mkdir(parents=True, exist_ok=True)
    marker = tdir / ".vhs-ready"
    if marker.is_file():
        bindir = Path(marker.read_text(encoding="utf-8").strip())
        exe = bindir / ("vhs.exe" if sys.platform == "win32" else "vhs")
        if exe.is_file():
            _prepend_path(bindir)
            return

    asset, is_zip = _vhs_release_asset()
    url = VHS_DOWNLOAD_BASE + asset
    dl = tdir / asset
    _download(url, dl)
    if is_zip:
        with zipfile.ZipFile(dl) as zf:
            zf.extractall(tdir)
    else:
        with tarfile.open(dl, "r:gz") as tf:
            tf.extractall(tdir)
    dl.unlink(missing_ok=True)

    exe: Path | None = None
    for name in ("vhs.exe", "vhs"):
        for p in tdir.rglob(name):
            if p.is_file() and "completions" not in str(p):
                exe = p
                break
        if exe is not None:
            break
    if exe is None:
        raise RuntimeError("Could not find vhs executable in release archive")

    bindir = exe.parent
    if sys.platform != "win32":
        _chmod_plus_x(exe)
    marker.write_text(str(bindir), encoding="utf-8")
    _prepend_path(bindir)


def ensure_ffmpeg_ffprobe_on_path() -> None:
    import shutil

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return

    if sys.platform.startswith("linux"):
        _ensure_linux_ffmpeg_static()
    elif sys.platform == "darwin":
        _ensure_macos_ffmpeg_zips()
    elif sys.platform == "win32":
        _ensure_windows_ffmpeg_zip()
    else:
        raise OSError(f"Unsupported platform for bundled ffmpeg: {sys.platform}")


def _ensure_linux_ffmpeg_static() -> None:
    root = bin_cache_root() / "linux-ffmpeg"
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".ready"
    inner: Path | None = None
    if marker.is_file():
        name = marker.read_text(encoding="utf-8").strip()
        cand = root / name
        if cand.is_dir() and (cand / "ffmpeg").is_file() and (cand / "ffprobe").is_file():
            inner = cand
    if inner is None:
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        elif machine in ("aarch64", "arm64"):
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
        else:
            raise OSError(f"Unsupported Linux arch for static ffmpeg: {machine}")
        archive = root / "dist.tar.xz"
        _download(url, archive)
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(root)
        archive.unlink(missing_ok=True)
        inner = next(root.glob("ffmpeg-*-static"))
        _chmod_plus_x(inner / "ffmpeg")
        _chmod_plus_x(inner / "ffprobe")
        marker.write_text(inner.name, encoding="utf-8")
    _prepend_path(inner)


def _ensure_macos_ffmpeg_zips() -> None:
    d = bin_cache_root() / "mac-ffmpeg"
    d.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = d / "ffmpeg"
    ffprobe_bin = d / "ffprobe"
    if ffmpeg_bin.is_file() and ffprobe_bin.is_file():
        _chmod_plus_x(ffmpeg_bin)
        _chmod_plus_x(ffprobe_bin)
        _prepend_path(d)
        return

    for url in (EVERMEET_FFMPEG_ZIP, EVERMEET_FFPROBE_ZIP):
        side = d / ("_ffmpeg_dl.zip" if "ffmpeg" in url else "_ffprobe_dl.zip")
        _download(url, side)
        with zipfile.ZipFile(side) as zf:
            zf.extractall(d)
        side.unlink(missing_ok=True)

    if not ffmpeg_bin.is_file() or not ffprobe_bin.is_file():
        raise RuntimeError("evermeet ffmpeg/ffprobe zips did not produce ffmpeg + ffprobe binaries")

    _chmod_plus_x(ffmpeg_bin)
    _chmod_plus_x(ffprobe_bin)
    _prepend_path(d)


def _ensure_windows_ffmpeg_zip() -> None:
    root = bin_cache_root() / "win-ffmpeg"
    root.mkdir(parents=True, exist_ok=True)
    existing = next(root.rglob("bin/ffmpeg.exe"), None)
    if existing is not None:
        _prepend_path(existing.parent)
        return

    zpath = root / "ffmpeg.zip"
    _download(WIN_FFMPEG_ZIP, zpath)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(root)
    zpath.unlink(missing_ok=True)
    ff = next(root.rglob("bin/ffmpeg.exe"), None)
    if ff is None:
        raise RuntimeError("Windows ffmpeg zip missing bin/ffmpeg.exe")
    _prepend_path(ff.parent)


def bootstrap_ffmpeg_for_tests() -> None:
    """Put ffmpeg + ffprobe on PATH (compose / validate tests; no VHS)."""
    import shutil

    _augment_common_path_prefixes()
    ensure_ffmpeg_ffprobe_on_path()
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise RuntimeError(
            "ffmpeg and ffprobe must be on PATH after bootstrap "
            "(see tests/_render_tools_bootstrap.py)."
        )


def bootstrap_cli_render_toolchain() -> None:
    """Populate PATH with ffmpeg, ffprobe, and vhs when missing."""
    import shutil

    _augment_common_path_prefixes()
    ensure_ffmpeg_ffprobe_on_path()
    ensure_vhs_on_path()
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise RuntimeError(
            "ffmpeg and ffprobe must be on PATH after bootstrap "
            "(see tests/_render_tools_bootstrap.py)."
        )
    if shutil.which("vhs") is None:
        raise RuntimeError("vhs must be on PATH after bootstrap (see tests/_render_tools_bootstrap.py).")
