"""Actual browser-side HTTP downloads through the same authenticated Desktop BFF."""

import http.client
import io
import select
import threading
import time
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zipfile import ZIP_STORED, ZipFile

import pytest

from backend_manager.control_server import ControlServer
from backend_manager.web_bff import BridgeContext
from tests.test_control_auth import _bootstrap_cookie_header


@contextmanager
def _bridge(tmp_path, deliver, *, method="GET", headers=None):
    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            assert self.path == "/web/export/portable?ledger_id=archived"
            assert self.headers["Authorization"] == "Bearer retained-desktop-identity"
            with suppress(BrokenPipeError, ConnectionResetError):
                deliver(self)

        def do_HEAD(self):
            self.do_GET()

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)

    class Controller:
        def is_manager_shutting_down(self):
            return False

        def product_bridge_context(self):
            return BridgeContext(f"http://127.0.0.1:{backend.server_port}", "retained-desktop-identity")

        def note_product_bridge_auth_failure(self, _status, _token):
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    manager = ControlServer("127.0.0.1", 0, controller=Controller(), token="local-control",
        instance_secret="local-instance", ui_html=ui)
    threads = [threading.Thread(target=server.serve_forever) for server in (backend, manager)]
    for thread in threads:
        thread.start()
    try:
        cookie = _bootstrap_cookie_header(manager, tmp_path)
        client = http.client.HTTPConnection("127.0.0.1", manager.server_address[1], timeout=3)
        try:
            client.request(method, "/web/export/portable?ledger_id=archived",
                headers={"Cookie": cookie, **(headers or {})})
            yield client
        finally:
            client.close()
    finally:
        for server in (manager, backend):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def _headers(handler, size):
    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Length", str(size))
    handler.send_header("Content-Disposition", 'attachment; filename="ticketbox-portable.zip"')
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def test_download_reaches_browser_before_backend_finishes_and_reopens_complete_zip(tmp_path):
    archive = io.BytesIO()
    with ZipFile(archive, "w", ZIP_STORED) as bundle:
        bundle.writestr("manifest.json", '{"ledger_id":"archived"}')
        bundle.writestr("records.ndjson", b'{"amount_cents":1400}\n' * 100000)
    body = archive.getvalue()
    finish = threading.Event()

    def deliver(handler):
        _headers(handler, len(body))
        handler.wfile.write(body[:65536])
        handler.wfile.flush()
        assert finish.wait(5), "Desktop buffered the complete package before browser delivery"
        handler.wfile.write(body[65536:])

    try:
        with _bridge(tmp_path, deliver) as client:
            response = client.getresponse()
            assert response.status == 200 and response.getheader("Cache-Control") == "no-store"
            first = response.read(65536)
            assert first == body[:65536]
            finish.set()
            saved = tmp_path / "download.zip"
            with saved.open("wb") as output:
                output.write(first)
                while chunk := response.read(65536):
                    output.write(chunk)
            with ZipFile(saved) as bundle:
                assert bundle.testzip() is None
                assert bundle.read("manifest.json") == b'{"ledger_id":"archived"}'
                assert len(bundle.read("records.ndjson").splitlines()) == 100000
    finally:
        finish.set()


def test_browser_cancel_during_preparation_closes_backend_request(tmp_path):
    preparing, cancelled = threading.Event(), threading.Event()

    def deliver(handler):
        preparing.set()
        if select.select([handler.connection], [], [], 5)[0] and handler.connection.recv(1) == b"":
            cancelled.set()

    with _bridge(tmp_path, deliver) as client:
        assert preparing.wait(2)
        client.close()
        assert cancelled.wait(2), "The abandoned request kept preparing the sensitive package"


def test_truncated_backend_package_is_a_failed_download(tmp_path):
    def deliver(handler):
        _headers(handler, 100000)
        handler.wfile.write(b"partial archive")

    with _bridge(tmp_path, deliver) as client:
        response = client.getresponse()
        assert response.status == 200
        with pytest.raises(http.client.IncompleteRead):
            response.read()


def test_browser_cancel_during_delivery_closes_retained_backend_response(tmp_path):
    cancelled = threading.Event()

    def deliver(handler):
        _headers(handler, 1000000)
        handler.wfile.write(b"x" * 65536)
        handler.wfile.flush()
        if select.select([handler.connection], [], [], 5)[0] and handler.connection.recv(1) == b"":
            cancelled.set()

    with _bridge(tmp_path, deliver) as client:
        response = client.getresponse()
        assert len(response.read(65536)) == 65536
        response.close()
        client.close()
        assert cancelled.wait(2), "Backend response survived the cancelled browser download"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_portable_range_and_head_keep_file_metadata(tmp_path, method):
    def deliver(handler):
        assert handler.headers["Range"] == "bytes=1-3"
        handler.send_response(206)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header("Content-Length", "3")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Range", "bytes 1-3/100")
        handler.end_headers()
        if method == "GET":
            handler.wfile.write(b"123")

    with _bridge(tmp_path, deliver, method=method, headers={"Range": "bytes=1-3"}) as client:
        response = client.getresponse()
        assert response.status == 206
        assert response.getheader("Content-Range") == "bytes 1-3/100"
        assert response.getheader("Content-Length") == "3"
        assert response.read() == (b"123" if method == "GET" else b"")


def test_preparation_longer_than_ordinary_web_timeout_still_downloads(tmp_path):
    def deliver(handler):
        time.sleep(16)
        _headers(handler, 8)
        handler.wfile.write(b"complete")

    with _bridge(tmp_path, deliver) as client:
        client.sock.settimeout(22)
        response = client.getresponse()
        assert response.status == 200 and response.read() == b"complete"
