"""Fixtures for Playwright e2e tests — starts the wizard Flask app on a free port."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from docgen.config import Config
from docgen.wizard import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def project_dir(tmp_path_factory) -> Path:
    """Create a minimal docgen project tree used by all e2e tests."""
    root = tmp_path_factory.mktemp("project")

    (root / "docs").mkdir()
    (root / "docs" / "setup.md").write_text(
        "# Setup Guide\n\nInstall dependencies with pip.\n\n## Configure\n\nEdit config.yaml.\n",
        encoding="utf-8",
    )
    (root / "docs" / "architecture.md").write_text(
        "# Architecture\n\nModular pipeline approach.\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# Test Project\n\nA demo project.\n", encoding="utf-8")

    for d in ("narration", "audio", "animations", "terminal", "recordings"):
        (root / d).mkdir()

    (root / "narration" / "01-intro.md").write_text(
        "Welcome to the test project. This is the intro narration.\n", encoding="utf-8"
    )
    (root / "narration" / "02-setup.md").write_text(
        "Now we walk through the setup process.\n", encoding="utf-8"
    )

    cfg_data = {
        "dirs": {
            "narration": "narration",
            "audio": "audio",
            "animations": "animations",
            "terminal": "terminal",
            "recordings": "recordings",
        },
        "segments": {
            "all": ["01-intro", "02-setup"],
            "default": ["01-intro", "02-setup"],
        },
        "repo_root": ".",
        "wizard": {
            "exclude_patterns": ["**/archive/**"],
        },
    }
    (root / "docgen.yaml").write_text(
        json.dumps(cfg_data, indent=2) + "\n", encoding="utf-8"
    )

    # git init so repo_root detection works
    (root / ".git").mkdir()

    return root


@pytest.fixture(autouse=True)
def reset_project_state(project_dir):
    """Reset narration files and wizard state before each test so tests are isolated."""
    (project_dir / "narration" / "01-intro.md").write_text(
        "Welcome to the test project. This is the intro narration.\n", encoding="utf-8"
    )
    (project_dir / "narration" / "02-setup.md").write_text(
        "Now we walk through the setup process.\n", encoding="utf-8"
    )
    state_file = project_dir / ".docgen-state.json"
    if state_file.exists():
        state_file.unlink()
    yield


@pytest.fixture(scope="session")
def wizard_url(project_dir) -> str:
    """Start the Flask wizard on a free port and yield its base URL."""
    cfg = Config.from_yaml(project_dir / "docgen.yaml")
    app = create_app(cfg)
    port = _free_port()
    server = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    yield url
    server.shutdown()
