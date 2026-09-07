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
        ".ruff_cache",
        "dist",
        "build",
        "recordings",
        "media",
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
    """Turn ``org/repo`` / GitHub web URLs into an https clone URL.

    Strips ``/tree/…``, ``/blob/…``, query strings, and fragments so a pasted
    GitHub page URL still clones the repository.
    """
    s = spec.strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if s.startswith("www.github.com/"):
        s = "https://" + s
    if s.startswith("github.com/"):
        s = "https://" + s
    elif _GITHUB_SHORTHAND.fullmatch(s) and not _GIT_URL_PREFIX.match(s):
        s = f"https://github.com/{s}"
    if s.startswith("git@github.com:"):
        rest = s[len("git@github.com:") :]
        if rest.endswith(".git"):
            rest = rest[: -len(".git")]
        parts = [p for p in rest.split("/") if p]
        if len(parts) >= 2:
            return f"https://github.com/{parts[0]}/{parts[1]}.git"
        return s
    marker = "github.com/"
    idx = s.lower().find(marker)
    if idx >= 0 and s.lower().startswith(("http://", "https://")):
        rest = s[idx + len(marker) :]
        if rest.endswith(".git"):
            rest = rest[: -len(".git")]
        parts = [p for p in rest.split("/") if p]
        if len(parts) >= 2:
            return f"https://github.com/{parts[0]}/{parts[1]}.git"
    if s.startswith("https://github.com/") and not s.endswith(".git"):
        s = s + ".git"
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
    """Directory name for a cached clone.

    Uses ``owner-repo`` so ``acme/app`` and ``other/app`` do not share a folder.
    """
    raw = url.rstrip("/")
    if raw.endswith(".git"):
        raw = raw[: -len(".git")]
    if "://" in raw:
        raw = raw.split("://", 1)[1]
        raw = raw.split("/", 1)[-1] if "/" in raw else raw
    elif ":" in raw:
        raw = raw.split(":", 1)[-1]
    bits = [p for p in raw.replace("\\", "/").split("/") if p]
    if len(bits) >= 2:
        return f"{bits[-2]}-{bits[-1]}"
    return bits[-1] if bits else "repo"


def find_bundle_yaml(repo_root: Path) -> Path | None:
    """Locate ``docgen.yaml`` under a consumer checkout (children, not parents).

    :meth:`Config.discover` walks *up*. A ``--repo`` path is usually the git
    root, so the canonical bundle ``docs/demos/docgen.yaml`` would be missed.
    """
    root = repo_root.resolve()
    preferred = (
        root / "docs" / "demos" / "docgen.yaml",
        root / "demos" / "docgen.yaml",
        root / "docgen.yaml",
    )
    for path in preferred:
        if path.is_file():
            return path
    if not root.is_dir():
        return None
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        if "docgen.yaml" in filenames:
            found.append(Path(dirpath) / "docgen.yaml")
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
    if _looks_like_missing_local_path(raw, local) or not looks_like_git_url(raw):
        raise TargetRepoError(
            f"repo path does not exist: {local}. Pass a local checkout or a "
            "git URL / GitHub org/repo."
        )
    if not clone:
        raise TargetRepoError(f"repo is a git URL but clone is disabled: {raw}")
    url = normalize_git_url(raw)
    dest = (cache_dir or default_cache_dir()) / repo_cache_name(url)
    if (dest / ".git").exists():
        origin = _git_origin_url(dest)
        if origin and _remote_urls_differ(origin, url):
            raise TargetRepoError(
                f"clone cache {dest} is origin {origin!r}, not {url!r}; "
                "set DOCGEN_REPO_CACHE or remove the directory."
            )
        _try_update_cached_clone(dest, url)
        return dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise TargetRepoError(
            f"clone destination {dest} exists and is not a git checkout; "
            "set DOCGEN_REPO_CACHE or remove the directory."
        )
    clone_git_repo(url, dest)
    return dest.resolve()


def _looks_like_missing_local_path(raw: str, local: Path) -> bool:
    """True when ``raw`` is a filesystem path, not GitHub ``org/repo`` shorthand.

    ``docs/demos`` matches the shorthand regex, but if ``docs/`` exists it is a
    typo'd local path — do not clone ``github.com/docs/demos``.
    """
    s = raw.strip()
    if s.startswith(("./", "../", ".\\", "~")) or local.is_absolute():
        return True
    parent = local.parent
    return parent != Path(".") and parent.exists()


def _git_origin_url(dest: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(dest), "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    url = (result.stdout or "").strip()
    return url or None


def _remote_urls_differ(left: str, right: str) -> bool:
    def _canon(url: str) -> str:
        return normalize_git_url(url).rstrip("/").lower().removesuffix(".git")

    return _canon(left) != _canon(right)


def _git_auth_env(url: str) -> dict[str, str]:
    """Put a GitHub token in the child env, not on the argv that ``ps`` shows.

    Appends a ``GIT_CONFIG_KEY_*`` slot instead of overwriting a count the
    parent process already set (CI images often inject ``user.name`` this way).
    """
    env = os.environ.copy()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not (token and "github.com" in url and url.startswith("https://")):
        return env
    try:
        count = max(0, int(env.get("GIT_CONFIG_COUNT") or "0"))
    except ValueError:
        count = 0
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    env[f"GIT_CONFIG_KEY_{count}"] = (
        f"url.https://x-access-token:{token}@github.com/.insteadOf"
    )
    env[f"GIT_CONFIG_VALUE_{count}"] = "https://github.com/"
    return env


def _try_update_cached_clone(dest: Path, url: str) -> None:
    """Best-effort fetch of remote HEAD + hard reset so a reused cache tracks default branch.

    ``git fetch origin`` (no ref) can leave ``FETCH_HEAD`` on an arbitrary last
    ref. Always fetch ``origin HEAD`` so the working tree matches the remote
    default branch.
    """
    env = _git_auth_env(url)
    try:
        fetched = subprocess.run(
            ["git", "-C", str(dest), "fetch", "--depth", "1", "--quiet", "origin", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        if fetched.returncode != 0:
            return
        subprocess.run(
            ["git", "-C", str(dest), "reset", "--hard", "--quiet", "FETCH_HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
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
