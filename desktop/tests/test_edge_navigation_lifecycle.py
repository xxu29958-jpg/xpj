"""Real document transitions must not spend the final page's probe budget."""
from __future__ import annotations

import contextlib
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend_manager.desktop_shell import discover_edge_executable
from tests import _edge_cdp


@pytest.mark.skipif(os.name != "nt", reason="Windows Edge harness")
def test_intermediate_complete_page_does_not_spend_final_document_probe_budget(tmp_path: Path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/start":
                body = b"<!doctype html><script>setTimeout(()=>location.replace('/web'),200)</script>"
            elif self.path == "/web":
                body = b"<!doctype html><main id='main-content'>Final document</main><script defer src='/slow.js'></script>"
            elif self.path == "/slow.js":
                time.sleep(11)
                body = b"window.documentProbe='final-loaded'"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript" if self.path.endswith('.js') else "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(ConnectionError):
                self.wfile.write(body)
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    edge = discover_edge_executable()
    assert edge is not None
    try:
        result = _edge_cdp.evaluate_page(edge, profile=tmp_path/'edge',
            prepare_url=lambda _: origin+'/start', width=1180, height=760,
            document_url_prefix=origin+"/web",
            expression="document.readyState === 'complete' ? window.documentProbe : undefined")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
    assert result == "final-loaded"
    assert requests.count('/web') == 1
    assert requests.count('/slow.js') == 1


def _navigated(frame, loader, url):
    return {"method": "Page.frameNavigated", "params": {"frame": {"id": frame, "loaderId": loader, "url": url}}}


def _loaded(frame, loader):
    return {"method": "Page.lifecycleEvent", "params": {"frameId": frame, "loaderId": loader, "name": "load"}}


def test_document_lifecycle_requires_current_main_loader_and_intended_url():
    page = _edge_cdp._WebSocket.__new__(_edge_cdp._WebSocket)
    page._events = deque([
        _navigated("main", "bootstrap", "file:///bootstrap.html"), _loaded("main", "bootstrap"),
        _navigated("main", "discarded", "http://localhost/web"),
        _navigated("main", "redirect", "http://localhost/api/bootstrap"), _loaded("main", "discarded"),
        _navigated("main", "current", "http://localhost/web/pending"),
        _loaded("child", "current"), _loaded("main", "discarded"), _loaded("main", "current"),
        {"method": "after-correct-load"},
    ])
    assert page.wait_for_document("main", "http://localhost/web", timeout=30)
    assert list(page._events) == [{"method": "after-correct-load"}]


def test_missing_main_load_is_document_timeout_not_renderer_evaluation(monkeypatch):
    page = _edge_cdp._WebSocket.__new__(_edge_cdp._WebSocket)
    page._events = deque([_navigated("main", "new", "http://localhost/web"), _loaded("child", "new")])
    page._socket = object()
    waits = []
    def select_ready(read, _write, _errors, timeout):
        waits.append((read, timeout))
        return [], [], []
    monkeypatch.setattr(_edge_cdp.select, "select", select_ready)
    assert not page.wait_for_document("main", "http://localhost/web", timeout=30)
    assert len(waits) == 1 and waits[0][0] == [page._socket]
    assert 29 < waits[0][1] <= 30


def test_cdp_command_response_preserves_interleaved_document_events():
    page = _edge_cdp._WebSocket.__new__(_edge_cdp._WebSocket)
    page._events = deque()
    page._next_id = 1
    event = _navigated("main", "accepted", "http://localhost/web")
    incoming = iter([event, {"id": 1, "result": {"frameId": "main"}}])
    page._send_frame = lambda _payload: None
    page._receive_json = lambda: next(incoming)
    assert page.request("Page.navigate", {"url": "file:///bootstrap.html"}) == {"frameId": "main"}
    assert list(page._events) == [event]
