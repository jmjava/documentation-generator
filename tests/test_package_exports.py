"""Smoke tests for `docgen` package-level re-exports."""

from docgen import manifest_from_mapping, render


def test_manifest_from_mapping_exported_at_package_root() -> None:
    assert callable(manifest_from_mapping)
    assert callable(render)
