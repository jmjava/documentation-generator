"""docgen — reusable demo generation pipeline.

The package root re-exports the per-function demo API (`demo_function`) so
consumers can use ``from docgen import load_manifest, render`` without reaching
into submodules. For CLI / VHS demos (no Playwright tests), build a manifest with
`manifest_from_mapping` and pass it to `render`.
"""

from docgen.demo_function import (
    CACHED_ARTIFACTS,
    HARD_CAP_SECONDS,
    Action,
    EXIT_INVALID,
    EXIT_NEUTRAL_SKIP,
    EXIT_OK,
    EXIT_TOOLING_MISSING,
    Manifest,
    ManifestError,
    NarrationResult,
    PlaceholderManifest,
    RenderResult,
    SUPPORTED_ACTION_KINDS,
    ToolingMissingError,
    generate_capture_script,
    load_manifest,
    manifest_from_mapping,
    render,
    run_cli,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "Action",
    "CACHED_ARTIFACTS",
    "EXIT_INVALID",
    "EXIT_NEUTRAL_SKIP",
    "EXIT_OK",
    "EXIT_TOOLING_MISSING",
    "HARD_CAP_SECONDS",
    "Manifest",
    "ManifestError",
    "NarrationResult",
    "PlaceholderManifest",
    "RenderResult",
    "SUPPORTED_ACTION_KINDS",
    "ToolingMissingError",
    "generate_capture_script",
    "load_manifest",
    "manifest_from_mapping",
    "render",
    "run_cli",
]
