"""Semi-stable YAML catalog for discovered docs sources (Playwright tests, etc.).

After ``docgen discover-tests`` (planned), write the catalog (default
``<repo_root>/docgen.catalog.yaml``; see ``Config.catalog_file_path``).
Each **entry** records stable ids, bound segment ids, and **fingerprints** of
inputs. Downstream commands call :func:`entry_should_run` to decide whether to
skip work for that entry.

**When content changes**

Compare live SHA-256s (:func:`fingerprint_inputs`) to ``entries[].fingerprints.inputs``.
Any mismatch means that entry should run again, then :func:`refresh_entry_fingerprints`
and :func:`save_catalog` in the **same** successful CI job — so catalog updates stay
**action-driven** (explicit step), not implicit background sync.

**Overrides**

1. **Global** — ``global_force=True`` or env ``DOCGEN_CATALOG_FORCE_ALL=1`` / ``true``
   (see :func:`global_force_from_env`; used by ``docgen catalog stale``).
2. **Ephemeral by id** — ``force_ids`` from :func:`parse_force_id_list`, e.g. env
   ``DOCGEN_CATALOG_FORCE_IDS=id1,id2`` or ``workflow_dispatch`` inputs (no YAML edit).
3. **Pinned in repo** — ``policy: { regenerate: true }`` on an entry (or legacy
   ``regenerate: true``). Pipeline regens, then :func:`clear_regenerate_pin` and commits.

This complements the publish-time ``index.json`` contract (courseforge
``docgen-index-v1``): that file describes rendered outputs; this file drives
incremental regeneration from discovered sources.

Schema ``catalog_schema_version: 1`` — bump only on breaking shape changes.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CATALOG_FILENAME = "docgen.catalog.yaml"


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def new_catalog(*, repo_root: Path | None, docgen_version: str) -> dict[str, Any]:
    return {
        "catalog_schema_version": 1,
        "updated_at": utc_now_iso(),
        "docgen_version": docgen_version,
        "repo_root": str(repo_root.resolve()) if repo_root else None,
        "entries": [],
    }


def reset_catalog_for_repo(
    *,
    catalog_path: Path,
    repo_root: Path,
    docgen_version: str,
) -> None:
    """Write ``catalog_path`` with an empty ``entries`` list (same as ``docgen catalog reset -y``)."""
    save_catalog(catalog_path, new_catalog(repo_root=repo_root, docgen_version=docgen_version))


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Catalog must be a YAML mapping: {path}")
    ver = raw.get("catalog_schema_version")
    if ver != 1:
        raise ValueError(f"Unsupported catalog_schema_version: {ver!r} in {path}")
    if "entries" not in raw or not isinstance(raw["entries"], list):
        raw["entries"] = []
    return raw


def save_catalog(path: Path, data: dict[str, Any]) -> None:
    """Write catalog YAML; refreshes ``updated_at``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data["catalog_schema_version"] = 1
    data["updated_at"] = utc_now_iso()
    path.write_text(
        yaml.safe_dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def resolve_under_base(base: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (base / p)


def fingerprint_inputs(base: Path, tracked_paths: list[str]) -> dict[str, str | None]:
    """SHA-256 of each existing file; missing paths map to ``None``."""
    out: dict[str, str | None] = {}
    for rel in tracked_paths:
        ap = resolve_under_base(base, rel)
        out[rel] = sha256_file(ap)
    return out


def _stored_input_fingerprints(entry: dict[str, Any]) -> dict[str, str]:
    fp = entry.get("fingerprints")
    if not isinstance(fp, dict):
        return {}
    inputs = fp.get("inputs")
    if not isinstance(inputs, dict):
        return {}
    return {str(k): str(v) for k, v in inputs.items() if isinstance(v, str)}


def tracked_paths_for_entry(entry: dict[str, Any]) -> list[str]:
    """Paths to fingerprint for staleness checks."""
    fp = entry.get("fingerprints")
    if isinstance(fp, dict):
        tp = fp.get("tracked_paths")
        if isinstance(tp, list):
            return [str(x) for x in tp if x]
    return []


def entry_needs_regeneration(entry: dict[str, Any], repo_root: Path, *, force: bool = False) -> bool:
    """Return True if any tracked input changed or disappeared (vs catalog)."""
    if force:
        return True
    paths = tracked_paths_for_entry(entry)
    if not paths:
        return True
    live = fingerprint_inputs(repo_root, paths)
    stored = _stored_input_fingerprints(entry)
    for rel in paths:
        cur = live.get(rel)
        prev = stored.get(rel)
        if cur is None and prev is None:
            continue
        if cur is None or prev is None:
            return True
        if cur != prev:
            return True
    return False


def parse_force_id_list(raw: str | None) -> set[str]:
    """Parse comma-separated entry ids (e.g. from ``DOCGEN_CATALOG_FORCE_IDS``)."""
    if not raw or not str(raw).strip():
        return set()
    return {part.strip() for part in str(raw).split(",") if part.strip()}


def force_ids_from_env() -> set[str]:
    """Entry ids to force from ``DOCGEN_CATALOG_FORCE_IDS`` (empty if unset)."""
    return parse_force_id_list(os.environ.get("DOCGEN_CATALOG_FORCE_IDS"))


def global_force_from_env() -> bool:
    """True when ``DOCGEN_CATALOG_FORCE_ALL`` is set to a truthy value (``1``, ``true``, ``yes``)."""
    v = os.environ.get("DOCGEN_CATALOG_FORCE_ALL", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def entry_has_regenerate_pin(entry: dict[str, Any]) -> bool:
    """True if the entry was marked for an explicit regen (checked into git)."""
    pol = entry.get("policy")
    if isinstance(pol, dict) and pol.get("regenerate") is True:
        return True
    return entry.get("regenerate") is True


def clear_regenerate_pin(entry: dict[str, Any]) -> bool:
    """Clear ``policy.regenerate`` / ``regenerate`` after a successful run. Returns True if mutated."""
    mutated = False
    if entry.get("regenerate") is True:
        del entry["regenerate"]
        mutated = True
    pol = entry.get("policy")
    if isinstance(pol, dict) and pol.get("regenerate") is True:
        pol["regenerate"] = False
        mutated = True
    return mutated


def entry_should_run(
    entry: dict[str, Any],
    repo_root: Path,
    *,
    global_force: bool = False,
    force_ids: set[str] | None = None,
) -> bool:
    """Whether this catalog entry should be regenerated this run.

    Order: global force → id in ``force_ids`` → regenerate pin → fingerprint staleness.
    """
    if global_force:
        return True
    eid = str(entry.get("id", ""))
    if force_ids and eid in force_ids:
        return True
    if entry_has_regenerate_pin(entry):
        return True
    return entry_needs_regeneration(entry, repo_root, force=False)


def refresh_entry_fingerprints(entry: dict[str, Any], repo_root: Path) -> None:
    """Update ``entry['fingerprints']['inputs']`` from ``tracked_paths`` (mutates)."""
    paths = tracked_paths_for_entry(entry)
    if not paths:
        return
    if "fingerprints" not in entry or not isinstance(entry["fingerprints"], dict):
        entry["fingerprints"] = {}
    entry["fingerprints"]["tracked_paths"] = paths
    entry["fingerprints"]["inputs"] = fingerprint_inputs(repo_root, paths)


def merge_entries(
    catalog: dict[str, Any],
    new_entries: list[dict[str, Any]],
    *,
    replace_existing: bool = False,
) -> int:
    """Merge ``new_entries`` into ``catalog['entries']`` by ``id``.

    Returns number of entries added or replaced. When ``replace_existing`` is
    false, existing ids are left unchanged (discovery is idempotent).
    """
    existing: dict[str, dict[str, Any]] = {}
    for e in catalog.get("entries", []):
        if isinstance(e, dict) and e.get("id"):
            existing[str(e["id"])] = e
    changed = 0
    for e in new_entries:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        eid = str(e["id"])
        if eid in existing:
            if replace_existing:
                existing[eid].clear()
                existing[eid].update(e)
                changed += 1
        else:
            existing[eid] = e
            changed += 1
    catalog["entries"] = list(existing.values())
    return changed
