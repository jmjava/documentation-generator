"""Launch the Vue wizard in a desktop window (or a local browser fallback)."""

from __future__ import annotations

import socket
import threading
import time
import webbrowser
from typing import Any
from wsgiref.simple_server import make_server


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve_url(
    config: Any | None = None,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    path: str = "/?view=benchmark",
) -> tuple[str, Any]:
    """Start Flask in a daemon thread. Returns ``(url, httpd)``."""
    from docgen.wizard import create_app

    app = create_app(config)
    bind_port = int(port) if port else _free_port()
    httpd = make_server(host, bind_port, app)
    thread = threading.Thread(target=httpd.serve_forever, name="docgen-gui", daemon=True)
    thread.start()
    time.sleep(0.05)
    url = f"http://{host}:{bind_port}{path}"
    return url, httpd


def _wait_until_interrupt(httpd: Any) -> None:
    try:
        while True:
            time.sleep(0.4)
    except KeyboardInterrupt:
        httpd.shutdown()


def launch_desktop(
    config: Any | None = None,
    *,
    port: int | None = None,
    path: str = "/?view=benchmark",
    width: int = 1100,
    height: int = 760,
) -> str:
    """Open the GUI. Prefer ``pywebview``; fall back to the system browser.

    Returns the URL that was opened.
    """
    url, httpd = serve_url(config, port=port, path=path)
    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        _wait_until_interrupt(httpd)
        return url

    webview.create_window(
        "docgen",
        url,
        width=width,
        height=height,
        min_size=(800, 560),
    )
    webview.start()
    httpd.shutdown()
    return url
