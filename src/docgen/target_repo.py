"""Resolve a consumer git checkout for docgen without vendoring this library.

``docgen`` is an external pip tool. The *target* repository should keep only a
bundle (``docs/demos/docgen.yaml`` + hints/narration). This module locates that
bundle from a local path or clone URL so a Cloud / CI environment that has
docgen installed can generate against any consumer repo.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_GIT_URL_PREFIX = re.compile(r"^(?:https?://|git@|ssh://|git://)", re.I)
_GITHUB_SHORTHAND = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "archive",
        ".tox",
        ".mypy_cache",
        "dist",
        "build",
    }
)


class TargetRepoError(RuntimeError):
    """Raised when a ``--repo`` spec cannot be resolved or cloned."""


def looks_like_git_url(spec: str) -> bool:
    s = spec.strip()
    if not s:
        return False
    if _GIT_URL_PREFIX.match(s) or s.endswith(".git"):
        return True
    if s.startswith("github.com/"):
        return True
    if _GITHUB_SHORTHAND.fullmatch(s) and "/" in s:
        return True
    return False


def normalize_git_url(spec: str) -> str:
    """Turn ``org/repo`` / ``github.com/org/repo`` into an https clone URL."""
    s = spec.strip()
    if s.startswith("github.com/"):
        s = "https://" + s
    elif _GITHUB_SHORTHAND.fullmatch(s) and not _GIT_URL_PREFIX.match(s):
        s = f"https://github.com/{s}"
    if s.startswith("https://github.com/") and not s.endswith(".git"):
        s = s.rstrip("/") + ".git"
    return s


def default_cache_dir() -> Path:
    override = (os.environ.get("DOCGEN_REPO_CACHE") or "").strip()
    if override:
        return Path(override).expanduser()
    xdg = (os.environ.get("XDG_CACHE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "docgen" / "repos"
    return Path.home() / ".cache" / "docgen" / "repos"


def repo_cache_name(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name or "repo"


def find_bundle_yaml(repo_root: Path) -> Path | None:
    """Locate ``docgen.yaml`` under a consumer checkout (children, not parents).

    :meth:`Config.discover` walks *up*. A ``--repo`` path is usually the git
    root, so the canonical bundle ``docs/demos/docgen.yaml`` would be missed.
    """
    root = repo_root.resolve()
    preferred = (
        root / "docs" / "demos" / "docgen.yaml",
        root / "docgen.yaml",
    )
    for path in preferred:
        if path.is_file():
            return path
    found: list[Path] = []
    if not root.is_dir():
        return None
    for path in root.rglob("docgen.yaml"):
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in _SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        found.append(path)
    if not found:
        return None
    found.sort(
        key=lambda p: (
            0 if "demos" in p.parts else 1,
            len(p.relative_to(root).parts),
            str(p),
        )
    )
    return found[0]


def resolve_repo(
    spec: str,
    *,
    cache_dir: Path | None = None,
    clone: bool = True,
) -> Path:
    """Return a local checkout for ``spec`` (existing path or git URL)."""
    raw = (spec or "").strip()
    if not raw:
        raise TargetRepoError("empty --repo spec")
    local = Path(raw).expanduser()
    if local.exists():
        return local.resolve()
    if not looks_like_git_url(raw):
        raise TargetRepoError(
            f"repo path does not exist: {local}. Pass a local checkout or a "
            "git URL / GitHub org/repo."
        )
    if not clone:
        raise TargetRepoError(f"repo is a git URL but clone is disabled: {raw}")
    url = normalize_git_url(raw)
    dest = (cache_dir or default_cache_dir()) / repo_cache_name(url)
    if (dest / ".git").exists():
        _try_update_cached_clone(dest, url)
        return dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise TargetRepoError(
            f"clone destination {dest} exists and is not a git checkout; "
            "set DOCGEN_REPO_CACHE or remove the directory."
        )
    clone_git_repo(url, dest)
    return dest.resolve()


def _git_auth_env(url: str) -> dict[str, str]:
    """Put a GitHub token in the child env, not on the argv that ``ps`` shows."""
    env = os.environ.copy()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token and "github.com" in url and url.startswith("https://"):
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = f"url.https://x-access-token:{token}@github.com/.insteadOf"
        env["GIT_CONFIG_VALUE_0"] = "https://github.com/"
    return env


def _try_update_cached_clone(dest: Path, url: str) -> None:
    """Best-effort ``git fetch`` so a reused ``DOCGEN_REPO_CACHE`` is not forever stale."""
    try:
        subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth", "1", "--quiet", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=_git_auth_env(url),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return


def clone_git_repo(url: str, dest: Path) -> None:
    """Shallow-clone ``url`` into ``dest`` (uses GITHUB_TOKEN / GH_TOKEN when set)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            env=_git_auth_env(url),
        )
    except FileNotFoundError as exc:
        raise TargetRepoError("git is not installed; cannot clone --repo") from exc
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or "").strip()
        raise TargetRepoError(f"git clone failed for {url}: {err or exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TargetRepoError(f"git clone timed out for {url}") from exc
