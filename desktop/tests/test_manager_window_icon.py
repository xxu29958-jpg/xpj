"""The Manager window carries the packaged product icon, not Edge's generic globe.

Edge ``--app`` windows take their window and taskbar icon from the page favicon. The
Manager serves backend/packaging/ticketbox.ico (the same file as the executable and
installer icon) at /favicon.ico; the Windows gate reads the icon Windows actually holds
for the real Edge window and compares it with that file.
"""

from __future__ import annotations

import http.client
import os
import re
import struct
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend_manager import desktop_shell, manager_startup
from backend_manager.control_server import ControlServer
from tests._manager_ui_test_support import _UI_HTML, _status

_PACKAGED_ICON = Path(__file__).resolve().parents[2] / "backend" / "packaging" / "ticketbox.ico"
# Thumbnail difference (0-255): a frame of the packaged icon scores <= ~6 after any
# resampling; Edge's outline globe or the previous document icon score ~60-85.
_MATCH = 15.0


class _Controller:
    def status(self) -> dict:
        return _status(degraded=False)

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def restart(self) -> None: ...
    def auto_restart(self) -> None: ...
    def open_console(self) -> None: ...

    def is_manager_shutting_down(self) -> bool:
        return False


def _serve(window_icon: Path | None) -> tuple[ControlServer, threading.Thread]:
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=_Controller(),
        token="window-icon-token",
        instance_secret="window-icon-secret",
        ui_html=_UI_HTML,
        window_icon=window_icon,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    return server, thread


def _stop(server: ControlServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join()


def _get(server: ControlServer, path: str, *, host: str | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    try:
        connection.putrequest("GET", path, skip_host=True)
        connection.putheader("Host", host or server.expected_host)
        connection.endheaders()
        response = connection.getresponse()
        return response.status, dict(response.headers.items()), response.read()
    finally:
        connection.close()


def test_manager_page_and_startup_use_the_packaged_icon() -> None:
    assert manager_startup._WINDOW_ICON == _PACKAGED_ICON
    head = _UI_HTML.read_text(encoding="utf-8").partition("</head>")[0]
    assert head.count('rel="icon"') == 1
    assert '<link rel="icon" href="/favicon.ico">' in head


def test_favicon_route_serves_the_packaged_icon_only_to_the_manager_host() -> None:
    server, thread = _serve(_PACKAGED_ICON)
    try:
        status, headers, body = _get(server, "/favicon.ico")
        assert status == 200
        assert headers["Content-Type"] == "image/x-icon"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "img-src 'self' data:" in headers["Content-Security-Policy"]
        assert body == _PACKAGED_ICON.read_bytes()

        assert _get(server, "/favicon.ico", host=f"evil.test:{server.server_address[1]}")[0] == 421
        assert _get(server, "/favicon.ico?v=1")[0] == 404
    finally:
        _stop(server, thread)


def test_favicon_route_is_absent_without_an_icon() -> None:
    server, thread = _serve(None)
    try:
        assert _get(server, "/favicon.ico")[0] == 404
    finally:
        _stop(server, thread)


def _icon_frame_sizes(path: Path) -> list[int]:
    data = path.read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    return sorted({data[6 + 16 * index] or 256 for index in range(count)})


_PRODUCT_STATIC = Path(__file__).resolve().parents[2] / "backend" / "app"
_PRODUCT_ICON_LINK = re.search(
    r'<link rel="icon"[^>]*>', (_PRODUCT_STATIC / "templates" / "web" / "base.html").read_text(encoding="utf-8")
).group(0)


class _ProductBackend(ThreadingHTTPServer):
    """Stands in for the product backend behind the Manager's /web bridge."""

    def __init__(self, page: str) -> None:
        super().__init__(("127.0.0.1", 0), _ProductHandler)
        self.page = page
        self.seen: list[str] = []


class _ProductHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        server: _ProductBackend = self.server  # type: ignore[assignment]
        server.seen.append(self.path)
        path = urllib.parse.urlsplit(self.path).path
        if path == "/web":
            body, content_type = server.page.encode("utf-8"), "text/html; charset=utf-8"
        elif path.startswith("/static/web/product/brand/") and (_PRODUCT_STATIC / path.removeprefix("/")).is_file():
            body, content_type = (_PRODUCT_STATIC / path.removeprefix("/")).read_bytes(), "image/png"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _BridgedController(_Controller):
    def __init__(self, backend: _ProductBackend) -> None:
        self._backend = backend

    def product_bridge_context(self):
        from backend_manager.web_bff import BridgeContext

        return BridgeContext(f"http://127.0.0.1:{self._backend.server_port}", "window-icon-app-token")

    def note_product_bridge_auth_failure(self, _status: int, _token: str) -> bool:
        return False


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge app-window gate")
@pytest.mark.parametrize(
    ("scenario", "page"),
    [
        # The production bootstrap lands on the bridged product app with base.html's favicon.
        ("product", f"<!doctype html><html><head><title>小票夹</title>{_PRODUCT_ICON_LINK}</head><body>web</body></html>"),
        # The Manager page itself (ui.html, /favicon.ico) reached from the same window.
        ("manager", '<!doctype html><html><head><meta http-equiv="refresh" content="0;url=/"></head></html>'),
    ],
)
def test_real_manager_window_shows_the_packaged_icon(tmp_path: Path, monkeypatch, scenario: str, page: str) -> None:
    from backend_manager import control_server
    from tests import _window_icon

    assert desktop_shell.discover_edge_executable() is not None, "Microsoft Edge is required"
    evidence = Path(os.environ.get("TICKETBOX_WINDOW_ICON_EVIDENCE") or tmp_path / "evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    expected = {
        size: _window_icon.thumbnail(*_window_icon.file_icon(_PACKAGED_ICON, size))
        for size in _icon_frame_sizes(_PACKAGED_ICON)
    }
    responses: list[tuple[str, int]] = []
    original_send_response = control_server._Handler.send_response

    def recording_send_response(handler, code, message=None):
        responses.append((handler.path, code))
        original_send_response(handler, code, message)

    monkeypatch.setattr(control_server._Handler, "send_response", recording_send_response)
    backend = _ProductBackend(page)
    backend_thread = threading.Thread(target=backend.serve_forever)
    backend_thread.start()
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=_BridgedController(backend),
        token="window-icon-token",
        instance_secret="window-icon-secret",
        ui_html=_UI_HTML,
        window_icon=manager_startup._WINDOW_ICON,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    window = None
    observations: list[tuple[int, int, float]] = []
    matched = False
    try:
        bootstrap = server.prepare_web_bootstrap(tmp_path / "launch" / "bootstrap.html")
        window = desktop_shell.open_app_window(bootstrap, profile=tmp_path / "edge-profile")
        assert window is not None
        deadline = time.monotonic() + 45
        while not matched and time.monotonic() < deadline:
            for handle in _window_icon.top_level_windows(window.process.pid):
                icon = _window_icon.window_icon(handle)
                if icon is None:
                    continue
                score = min(
                    _window_icon.difference(_window_icon.thumbnail(*icon), frame) for frame in expected.values()
                )
                if not observations or observations[-1] != (icon[0], icon[1], round(score, 1)):
                    observations.append((icon[0], icon[1], round(score, 1)))
                (evidence / f"{scenario}-window-icon.png").write_bytes(_window_icon.png(*icon))
                matched = matched or score <= _MATCH
            time.sleep(0.25)
        # Let the taskbar repaint before keeping the screen as human-readable evidence.
        time.sleep(1.5)
        (evidence / f"{scenario}-screen.png").write_bytes(_window_icon.png(*_window_icon.screen_rgba()))
    finally:
        trace = {"icon": observations, "manager": responses, "backend": backend.seen}
        (evidence / f"{scenario}-trace.txt").write_text(repr(trace), encoding="utf-8")
        if window is not None:
            window.close(timeout=5)
        _stop(server, thread)
        backend.shutdown()
        backend.server_close()
        backend_thread.join()
    assert matched, trace
