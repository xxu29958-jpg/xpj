"""Real Edge -> Manager session -> Web BFF -> loopback consumer contract."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from backend_manager.control_server import ControlServer
from backend_manager.desktop_shell import discover_edge_executable
from backend_manager.web_bff import BRIDGE_HEADER, BRIDGE_VERSION, BridgeContext
from tests._edge_cdp import evaluate_page

_APP_TOKEN = "desktop-e2e-app-token"
_CONTROL_TOKEN = "desktop-e2e-control-token"
_INSTANCE_SECRET = "desktop-e2e-instance-secret"
_BROWSER_SECRET = "browser-secret-must-not-reach-backend"
_RESPONSE_SECRET = "backend-secret-must-not-reach-browser"
_THEME_SCRIPT = (
    Path(__file__).parents[2]
    / "backend"
    / "app"
    / "static"
    / "web"
    / "desktop"
    / "theme.js"
).read_bytes()

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="The Desktop product consumer is Microsoft Edge on Windows.",
)

_CONSUMER_HTML = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>桌面桥真实消费者</title></head>
<body>
  <main>
    <h1 id="consumer-title">桌面桥真实消费者</h1>
    <button id="primary-interaction" type="button">发送真实请求</button>
    <output id="consumer-output" role="status">等待操作</output>
  </main>
  <script src="/static/web/desktop-e2e-consumer.js" defer></script>
</body>
</html>
"""

_CONSUMER_SCRIPT = f"""
const button = document.getElementById("primary-interaction");
const output = document.getElementById("consumer-output");
document.body.dataset.consumerReady = "true";
button.addEventListener("click", async () => {{
  button.disabled = true;
  document.cookie = "browser_secret={_BROWSER_SECRET}; Path=/web; SameSite=Strict";
  let probe;
  try {{
    const response = await fetch("/web/consumer", {{
      method: "POST",
      headers: {{
        "Content-Type": "application/json",
        "Authorization": "Bearer browser-forged-token",
        "X-Ticketbox-Desktop-Bridge": "browser-forged-bridge",
        "X-Control-Token": "browser-forged-control-token",
        "X-Client-Secret": "browser-forged-client-secret"
      }},
      body: JSON.stringify({{interaction: "primary"}})
    }});
    const payload = await response.json();
    const themeResponse = await fetch("/api/me/ui-preferences", {{
      method: "PUT",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{theme: "midnight"}})
    }});
    const themePayload = await themeResponse.json();
    output.textContent = payload.message;
    probe = {{
      ok: response.ok,
      status: response.status,
      message: payload.message,
      themeOk: themeResponse.ok,
      themeStatus: themeResponse.status,
      theme: themePayload.theme,
      responseSecret: response.headers.get("X-Backend-Secret"),
      cookie: document.cookie,
      title: document.title,
      heading: document.getElementById("consumer-title").textContent,
      path: location.pathname,
      search: location.search,
      buttonDisabled: button.disabled
    }};
  }} catch (error) {{
    probe = {{error: String(error), path: location.pathname}};
  }}
  document.body.dataset.consumerResult = JSON.stringify(probe);
}});
"""

_THEME_FAILURE_HTML = """<!doctype html>
<html lang="zh-CN" data-theme="paper" data-theme-sync="server">
<head><meta charset="utf-8"><title>主题失败反馈</title></head>
<body>
  <button type="button" data-theme-choice="midnight">玄夜</button>
  <p data-theme-sync-status role="status" aria-live="polite" hidden></p>
  <script src="/static/web/desktop/theme.js"></script>
  <script src="/static/web/desktop/theme-failure-fixture.js"></script>
</body>
</html>
"""

_THEME_FAILURE_SCRIPT = """
window.TicketboxWeb.THEMES = ["paper", "mono", "midnight"];
window.TicketboxWeb.initThemeToggle();
document.querySelector("[data-theme-choice=midnight]").click();
"""

_EDGE_PROBE = """
(() => {
  const body = document.body;
  const button = document.getElementById("primary-interaction");
  if (!body || body.dataset.consumerReady !== "true" || !button) return undefined;
  if (!globalThis.__ticketboxE2eClicked) {
    globalThis.__ticketboxE2eClicked = true;
    button.click();
    return undefined;
  }
  return body.dataset.consumerResult || undefined;
})()
"""

_THEME_FAILURE_PROBE = """
(() => {
  const status = document.querySelector("[data-theme-sync-status]");
  if (!status || status.hidden || !status.textContent) return undefined;
  return JSON.stringify({
    theme: document.documentElement.getAttribute("data-theme"),
    statusHidden: status.hidden,
    statusRole: status.getAttribute("role"),
    statusLive: status.getAttribute("aria-live"),
    statusText: status.textContent
  });
})()
"""


@dataclass(frozen=True)
class _ObservedRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class _AuditedConsumerServer(ThreadingHTTPServer):
    def __init__(self, *, theme_status: int = 200) -> None:
        super().__init__(("127.0.0.1", 0), _ConsumerHandler)
        self.requests: list[_ObservedRequest] = []
        self.theme_status = theme_status


class _ConsumerHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass

    def _record(self, body: bytes = b"") -> None:
        server = cast(_AuditedConsumerServer, self.server)
        server.requests.append(
            _ObservedRequest(
                method=self.command,
                path=self.path,
                headers={name.casefold(): value for name, value in self.headers.items()},
                body=body,
            )
        )

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        extra_headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._record()
        if self.path == "/web":
            server = cast(_AuditedConsumerServer, self.server)
            body = _THEME_FAILURE_HTML if server.theme_status != 200 else _CONSUMER_HTML
            self._send(200, body.encode(), "text/html; charset=utf-8")
            return
        if self.path == "/static/web/desktop-e2e-consumer.js":
            self._send(200, _CONSUMER_SCRIPT.encode(), "text/javascript; charset=utf-8")
            return
        if self.path == "/static/web/desktop/theme.js":
            self._send(200, _THEME_SCRIPT, "text/javascript; charset=utf-8")
            return
        if self.path == "/static/web/desktop/theme-failure-fixture.js":
            self._send(
                200,
                _THEME_FAILURE_SCRIPT.encode(),
                "text/javascript; charset=utf-8",
            )
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._record(body)
        if self.path != "/web/consumer":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        payload = json.dumps({"ok": True, "message": "真实请求已完成"}).encode()
        self._send(
            200,
            payload,
            "application/json; charset=utf-8",
            extra_headers=(
                ("X-Backend-Secret", _RESPONSE_SECRET),
                ("Set-Cookie", f"backend_secret={_RESPONSE_SECRET}; Path=/web"),
            ),
        )

    def do_PUT(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._record(body)
        if self.path != "/api/me/ui-preferences":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        server = cast(_AuditedConsumerServer, self.server)
        payload = (
            json.dumps({"theme": "midnight"})
            if server.theme_status == 200
            else json.dumps({"error": "permission_denied"})
        ).encode()
        self._send(server.theme_status, payload, "application/json; charset=utf-8")


@dataclass(frozen=True)
class _Controller:
    backend_origin: str

    def product_bridge_context(self) -> BridgeContext:
        return BridgeContext(backend_origin=self.backend_origin, app_token=_APP_TOKEN)


@contextmanager
def _serving(server: ThreadingHTTPServer) -> Iterator[None]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def _manager(tmp_path: Path, backend_origin: str) -> ControlServer:
    ui = tmp_path / "manager-placeholder.html"
    ui.write_text("<!doctype html><title>Manager</title>", encoding="utf-8")
    return ControlServer(
        "127.0.0.1",
        0,
        controller=_Controller(backend_origin),
        token=_CONTROL_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )


def _assert_bridge_request(request: _ObservedRequest, backend_origin: str) -> None:
    assert request.headers["authorization"] == f"Bearer {_APP_TOKEN}"
    assert request.headers[BRIDGE_HEADER.casefold()] == BRIDGE_VERSION
    assert request.headers["origin"] == backend_origin
    assert request.headers["referer"] == backend_origin + request.path
    assert request.headers["sec-fetch-site"] == "same-origin"
    assert "cookie" not in request.headers


def test_real_edge_navigates_manager_session_and_uses_bff_consumer(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Desktop BFF consumer gate"
    assert "window.fetch" not in _CONSUMER_SCRIPT
    consumer = _AuditedConsumerServer()
    backend_origin = f"http://127.0.0.1:{consumer.server_address[1]}"
    manager = _manager(tmp_path, backend_origin)
    bootstrap_path = tmp_path / "desktop-bootstrap.html"
    bootstrap_url = manager.prepare_web_bootstrap(bootstrap_path)
    assert _INSTANCE_SECRET not in bootstrap_url
    assert _INSTANCE_SECRET not in str(tmp_path / "edge-bff-e2e-profile")

    with _serving(consumer), _serving(manager):
        value = evaluate_page(
            edge,
            profile=tmp_path / "edge-bff-e2e-profile",
            url=bootstrap_url,
            width=820,
            height=660,
            expression=_EDGE_PROBE,
        )

    assert not bootstrap_path.exists()
    assert isinstance(value, str)
    dom = json.loads(value)
    assert dom == {
        "ok": True,
        "status": 200,
        "message": "真实请求已完成",
        "themeOk": True,
        "themeStatus": 200,
        "theme": "midnight",
        "responseSecret": None,
        "cookie": f"browser_secret={_BROWSER_SECRET}",
        "title": "桌面桥真实消费者",
        "heading": "桌面桥真实消费者",
        "path": "/web",
        "search": "",
        "buttonDisabled": True,
    }
    assert [(item.method, item.path) for item in consumer.requests] == [
        ("GET", "/web"),
        ("GET", "/static/web/desktop-e2e-consumer.js"),
        ("POST", "/web/consumer"),
        ("PUT", "/api/me/ui-preferences"),
    ]
    for request in consumer.requests:
        _assert_bridge_request(request, backend_origin)

    interaction = consumer.requests[-2]
    assert json.loads(interaction.body) == {"interaction": "primary"}
    theme_write = consumer.requests[-1]
    assert json.loads(theme_write.body) == {"theme": "midnight"}
    for sensitive_header in ("x-control-token", "x-client-secret"):
        assert sensitive_header not in interaction.headers
    serialized = json.dumps([request.headers for request in consumer.requests], sort_keys=True)
    assert _CONTROL_TOKEN not in serialized
    assert _INSTANCE_SECRET not in serialized
    assert "browser-forged-token" not in serialized
    assert "browser-forged-bridge" not in serialized


def test_real_edge_shows_visible_theme_sync_failure_for_non_2xx(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Desktop theme feedback gate"
    consumer = _AuditedConsumerServer(theme_status=403)
    backend_origin = f"http://127.0.0.1:{consumer.server_address[1]}"
    manager = _manager(tmp_path, backend_origin)
    bootstrap_url = manager.prepare_web_bootstrap(tmp_path / "theme-bootstrap.html")

    with _serving(consumer), _serving(manager):
        value = evaluate_page(
            edge,
            profile=tmp_path / "edge-theme-failure-profile",
            url=bootstrap_url,
            width=820,
            height=660,
            expression=_THEME_FAILURE_PROBE,
        )

    assert isinstance(value, str)
    assert json.loads(value) == {
        "theme": "midnight",
        "statusHidden": False,
        "statusRole": "status",
        "statusLive": "polite",
        "statusText": "主题已在此设备生效，但未能同步到其他设备。请稍后重试。",
    }
    assert [(request.method, request.path) for request in consumer.requests] == [
        ("GET", "/web"),
        ("GET", "/static/web/desktop/theme.js"),
        ("GET", "/static/web/desktop/theme-failure-fixture.js"),
        ("PUT", "/api/me/ui-preferences"),
    ]
