"""PyInstaller / ``python -m docgen.gui`` entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_config(config_path: str | None):
    if not config_path:
        return None
    from docgen.config import Config

    return Config.from_yaml(config_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="docgen desktop GUI (Vue + Flask).")
    parser.add_argument("--port", type=int, default=0, help="Bind port (0 = ephemeral).")
    parser.add_argument(
        "--view",
        default="benchmark",
        help="Initial wizard view (benchmark, setup, production, tool).",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Force the system browser instead of a pywebview window.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a consumer docgen.yaml (Setup / Production).",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Headless HTTP check of / and /api/benchmark; do not open a window.",
    )
    parser.add_argument(
        "--smoke-output",
        default=None,
        help="Write the --smoke JSON report to this path.",
    )
    args = parser.parse_args(argv)
    path = f"/?view={args.view}"
    port = args.port or None
    config = _load_config(args.config)
    if args.smoke:
        from docgen.gui.freeze import smoke_session

        out = Path(args.smoke_output) if args.smoke_output else None
        result = smoke_session(config, output=out)
        print(json.dumps(result, indent=2))
        return
    if args.browser:
        import webbrowser

        from docgen.gui.desktop import _wait_until_interrupt, serve_url

        url, httpd = serve_url(config, port=port, path=path)
        webbrowser.open(url)
        _wait_until_interrupt(httpd)
        return
    from docgen.gui.desktop import launch_desktop

    launch_desktop(config, port=port, path=path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"docgen-gui failed: {exc}", file=sys.stderr)
        raise
