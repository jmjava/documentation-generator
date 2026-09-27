"""Fitness function: src/docgen does not import a consumer repository."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "docgen"

_CONSUMER_NAMES = ("course-builder", "course_builder", "tekton-dag", "tekton_dag")
_HARDCODED_BUNDLE = re.compile(r"(?:^|[\s\"'])/(?:[\w.-]+/){2,}docs/demos\b")


def _consumer_ref(text: str) -> str | None:
    for name in _CONSUMER_NAMES:
        if name in text:
            return name
    if _HARDCODED_BUNDLE.search(text):
        return "hardcoded bundle"
    return None


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module or "", *[alias.name for alias in node.names]]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _offenders(path: Path, tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        for name in _imported_names(node):
            why = _consumer_ref(name)
            if why is not None:
                found.append(f"{path}:{getattr(node, 'lineno', 0)} {why}")
    return found


def test_src_docgen_does_not_import_consumer_repository() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(_offenders(path, tree))
    assert offenders == []
