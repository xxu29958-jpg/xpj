"""The Manager window carries the packaged product icon and no Edge translate prompt.

Edge ``--app`` windows take their window and taskbar icon from the page favicon. The
Manager serves backend/packaging/ticketbox.ico (the same file as the executable and
installer icon) at /favicon.ico; the Windows gate reads the icon Windows actually holds
for the real Edge window and compares it with that file.

On a Windows UI in another language Edge pops "Translate page from Chinese
(Simplified)?" over every Chinese page. Each document the window shows stays
lang="zh-CN" and is marked translate="no"; the Windows gate watches the real window
for the prompt, with an unmarked Manager page as the control that must raise it.
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
from typing import cast

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
        server = cast(_ProductBackend, self.server)
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


_WEB_TEMPLATES = _PRODUCT_STATIC / "templates" / "web"
# Every document the Manager window shows: its own page and the /web roots the bridge
# relays (/web/auth is not bridged).
_WINDOW_DOCUMENTS = (
    _UI_HTML,
    _WEB_TEMPLATES / "base.html",
    _WEB_TEMPLATES / "_currency_layout.html",
    _WEB_TEMPLATES / "inbox_read_error.html",
)
_NO_TRANSLATE = ' translate="no"'
# Seconds to keep watching once the page is up; the control's prompt comes well inside it.
_SETTLE = 8.0


def _html_root(document: Path) -> str:
    match = re.search(r"<html\b[^>]*>", document.read_text(encoding="utf-8"))
    assert match is not None, document
    return match.group(0)


@pytest.mark.parametrize("document", _WINDOW_DOCUMENTS, ids=lambda path: path.name)
def test_manager_window_documents_stay_chinese_and_are_not_for_translation(document: Path) -> None:
    root = _html_root(document)
    assert 'lang="zh-CN"' in root
    assert _NO_TRANSLATE in root


# A bridged product page: base.html's own root element (template values left empty)
# around enough Chinese for Edge to recognise the language.
_PRODUCT_PAGE = (
    "<!doctype html>"
    + re.sub(r"\{\{.*?\}\}", "", _html_root(_WEB_TEMPLATES / "base.html"))
    + '<head><meta charset="utf-8"><title>收件箱</title></head><body><main><h1>收件箱</h1>'
    "<p>拍下的小票先放在这里。核对金额、商家和日期以后，账单进入流水，原图随账单一起保留，随时可以对照。</p>"
    "<p>还有三张小票等待核对，最早的一张来自上周六的超市。</p></main></body></html>"
)
_TO_MANAGER_PAGE = '<!doctype html><html><head><meta http-equiv="refresh" content="0;url=/"></head></html>'


def _translate_scenario(scenario: str, tmp_path: Path) -> tuple[Path, str, str]:
    """(Manager page, bridged /web page, title of the page under watch)."""
    if scenario == "product":
        return _UI_HTML, _PRODUCT_PAGE, "收件箱"
    # DIAGNOSTIC: which markup Edge honours; removed once Windows evidence is in.
    if scenario == "product-unmarked":
        return _UI_HTML, _PRODUCT_PAGE.replace(_NO_TRANSLATE, "", 1), "收件箱"
    if scenario == "manager":
        return _UI_HTML, _TO_MANAGER_PAGE, "小票夹管理器"
    unmarked = _UI_HTML.read_text(encoding="utf-8").replace(_NO_TRANSLATE, "", 1)
    if scenario == "meta":
        unmarked = unmarked.replace(
            '<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta name="google" content="notranslate">', 1
        )
    manager_page = tmp_path / "ui.html"
    manager_page.write_text(unmarked, encoding="utf-8")
    return manager_page, _TO_MANAGER_PAGE, "小票夹管理器"


def _watch_for_prompt(process_id: int, title: str) -> dict[str, object]:
    """Watch until Edge raises a popup over the window, or for _SETTLE seconds once `title` is up."""
    from tests import _window_icon

    titles: list[str] = []
    shown_at: float | None = None
    started = time.monotonic()
    while (now := round(time.monotonic() - started, 2)) < 45:
        for handle in _window_icon.top_level_windows(process_id):
            name = _window_icon.window_title(handle)
            titles += [] if name in titles else [name]
            shown_at = now if shown_at is None and name.startswith(title) else shown_at
        popups = _window_icon.owned_popups(process_id)
        if popups:
            return {"titles": titles, "shown_at": shown_at, "prompt_at": now, "popups": popups}
        if shown_at is not None and now - shown_at >= _SETTLE:
            break
        time.sleep(0.25)
    return {"titles": titles, "shown_at": shown_at, "prompt_at": None, "popups": []}


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge app-window gate")
@pytest.mark.parametrize(
    ("scenario", "prompted"),
    [
        # Control: without the marker Edge must prompt on this runner, or the other cases prove nothing.
        ("unmarked", True),
        ("manager", False),
        ("product", False),
        ("meta", None),
        ("product-unmarked", None),
    ],
)
def test_real_manager_window_offers_no_translation(tmp_path: Path, scenario: str, prompted: bool | None) -> None:
    from tests import _window_icon

    assert desktop_shell.discover_edge_executable() is not None, "Microsoft Edge is required"
    evidence = Path(os.environ.get("TICKETBOX_WINDOW_ICON_EVIDENCE") or tmp_path / "evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    manager_page, page, title = _translate_scenario(scenario, tmp_path)
    backend = _ProductBackend(page)
    backend_thread = threading.Thread(target=backend.serve_forever)
    backend_thread.start()
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=_BridgedController(backend),
        token="window-translate-token",
        instance_secret="window-translate-secret",
        ui_html=manager_page,
        window_icon=manager_startup._WINDOW_ICON,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    window = None
    watched: dict[str, object] = {}
    try:
        bootstrap = server.prepare_web_bootstrap(tmp_path / "launch" / "bootstrap.html")
        window = desktop_shell.open_app_window(bootstrap, profile=tmp_path / "edge-profile")
        assert window is not None
        watched = _watch_for_prompt(window.process.pid, title)
        (evidence / f"translate-{scenario}-screen.png").write_bytes(_window_icon.png(*_window_icon.screen_rgba()))
    finally:
        trace = {**watched, "backend": backend.seen}
        (evidence / f"translate-{scenario}-trace.txt").write_text(repr(trace), encoding="utf-8")
        if window is not None:
            window.close(timeout=5)
        _stop(server, thread)
        backend.shutdown()
        backend.server_close()
        backend_thread.join()
    assert watched["shown_at"] is not None, trace
    if prompted is not None:
        assert (watched["prompt_at"] is not None) is prompted, trace
