"""Desktop GUI + freeze-safe resources (no PyInstaller run, no window)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from docgen.cli import main
from docgen.gui.packaging import pyinstaller_datas, pyinstaller_hiddenimports, spec_path
from docgen.resources import benchmark_data_dir, is_frozen, package_root, static_dir, templates_dir
from docgen.wizard import create_app


def test_package_root_uses_meipass(tmp_path: Path, monkeypatch) -> None:
    bundled = tmp_path / "docgen"
    (bundled / "templates").mkdir(parents=True)
    (bundled / "templates" / "wizard.html").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert is_frozen() is True
    assert package_root() == bundled
    assert (templates_dir() / "wizard.html").read_text(encoding="utf-8") == "ok"


def test_package_root_has_gui_assets() -> None:
    root = package_root()
    assert (root / "templates" / "wizard.html").is_file()
    assert (static_dir() / "benchmark-app.js").is_file()
    assert (static_dir() / "vendor" / "vue.global.prod.js").is_file()
    assert (templates_dir() / "wizard.html").is_file()
    assert (benchmark_data_dir() / "baseline.json").is_file()
    assert is_frozen() is False


def test_pyinstaller_datas_include_vue_and_baseline() -> None:
    dests = {dest for _src, dest in pyinstaller_datas()}
    assert "docgen/static" in dests
    assert "docgen/templates" in dests
    assert "docgen/benchmark_data" in dests
    assert "webview" in pyinstaller_hiddenimports()
    assert "docgen.gui.desktop" in pyinstaller_hiddenimports()


def test_pyinstaller_spec_exists_and_points_at_gui_entry() -> None:
    path = spec_path()
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "docgen.gui" in text or "__main__.py" in text
    assert "pyinstaller_datas" in text
    assert "excludes" in text


def test_wizard_html_is_vue_benchmark_shell() -> None:
    html = (templates_dir() / "wizard.html").read_text(encoding="utf-8")
    assert 'data-view="benchmark"' in html
    assert 'id="benchmark-app"' in html
    assert "vue.global.prod.js" in html
    assert "benchmark-app.js" in html
    assert "createApp" in (static_dir() / "benchmark-app.js").read_text(encoding="utf-8")


def test_api_benchmark_returns_corpus(tmp_path: Path) -> None:
    app = create_app(None)
    client = app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert b"benchmark-app" in page.data
    assert b"vue.global.prod.js" in page.data
    res = client.get("/api/benchmark")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["meets_baseline"] is True
    ids = {row["case_id"] for row in data["cases"]}
    assert "issue66_tight_clamped" in ids
    assert "issue66_tight_unclamped" in ids
    one = client.get("/api/benchmark?case=early_title")
    assert one.status_code == 200
    assert one.get_json()["cases"][0]["case_id"] == "early_title"
    bad = client.get("/api/benchmark?case=not-a-case")
    assert bad.status_code == 400


def test_api_benchmark_update_baseline_roundtrip(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "baseline.json"
    monkeypatch.setattr(
        "docgen.scene_benchmark.default_baseline_path",
        lambda: dest,
    )
    app = create_app(None)
    client = app.test_client()
    res = client.post("/api/benchmark/update-baseline")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["meets_baseline"] is True
    written = Path(data["wrote"])
    assert written == dest
    assert written.is_file()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert "issue66_tight_clamped" in payload["cases"]


def test_update_baseline_disabled_when_frozen(monkeypatch) -> None:
    monkeypatch.setattr("docgen.resources.is_frozen", lambda: True)
    app = create_app(None)
    res = app.test_client().post("/api/benchmark/update-baseline")
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_cli_registers_gui() -> None:
    assert "gui" in main.commands
    runner = CliRunner()
    result = runner.invoke(main, ["gui", "--help"])
    assert result.exit_code == 0
    assert "pywebview" in result.output or "desktop" in result.output.lower()
    from docgen.gui.__main__ import main as gui_main

    with pytest.raises(SystemExit) as exc:
        gui_main(["--help"])
    assert exc.value.code == 0
    from docgen.gui import launch_desktop, serve_url

    assert callable(launch_desktop) and callable(serve_url)




def test_serve_url_answers_benchmark(monkeypatch) -> None:
    from docgen.gui import desktop

    monkeypatch.setattr(desktop.time, "sleep", lambda _s: None)
    url, httpd = desktop.serve_url(None, path="/?view=benchmark")
    try:
        assert url.startswith("http://127.0.0.1:")
        import urllib.request

        api = url.split("?", 1)[0].rstrip("/") + "/api/benchmark?case=early_title"
        with urllib.request.urlopen(api, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["cases"][0]["case_id"] == "early_title"
    finally:
        httpd.shutdown()
