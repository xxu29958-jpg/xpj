"""Real Edge -> Manager session -> Web BFF -> backend contract.

Part A keeps the fake-consumer security matrix (secret non-leakage through
the relay). Part B drives the real chain: real backend on the dedicated
smoke DB, real desktop pairing through the manager endpoints, real
bootstrap, and real Edge rendering of the BFF-served /web.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest

from backend_manager import desktop_shell
from backend_manager.control_server import ControlServer
from backend_manager.desktop_shell import discover_edge_executable
from backend_manager.product_data import pair_product_session
from backend_manager.product_recovery import RebindRecovery
from backend_manager.web_bff import BRIDGE_HEADER, BRIDGE_VERSION, BridgeContext
from tests._edge_cdp import evaluate_page

# Fixture import: pytest collects ``real_backend`` as a fixture from this module's
# namespace even though it is defined in tests/_real_backend.py.
from tests._real_backend import (
    E2E_INSTALLATION_ID,
    CredentialStores,
    RealBackend,
    make_controller,
    make_manager,
    manager_bootstrap_cookies,
    manager_get,
    manager_post_json,
)

pytest_plugins = ["tests._real_backend"]

_APP_TOKEN = "desktop-e2e-app-token"
_CONTROL_TOKEN = "desktop-e2e-control-token"
_INSTANCE_SECRET = "desktop-e2e-instance-secret"
_BROWSER_SECRET = "browser-secret-must-not-reach-backend"
_RESPONSE_SECRET = "backend-secret-must-not-reach-browser"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_THEME_SCRIPT = (_REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop" / "theme.js").read_bytes()
_DESKTOP_BOOT_SCRIPT = (_REPO_ROOT / "backend" / "app" / "static" / "web" / "desktop.js").read_bytes()
_UI_HTML = _REPO_ROOT / "desktop" / "backend_manager" / "ui.html"

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
    output.textContent = payload.message;
    probe = {{
      ok: response.ok,
      status: response.status,
      message: payload.message,
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

_THEME_HTML = """<!doctype html>
<html lang="zh-CN" data-theme="paper">
<head><meta charset="utf-8"><title>主题桥接</title></head>
<body>
  <div id="appearance-popover" data-appearance-popover role="group" aria-label="主题">
    <button type="button" data-theme-mode="paper">晨纸</button>
    <button type="button" data-theme-mode="midnight">玄夜</button>
    <button type="button" data-theme-mode="system">跟随系统</button>
  </div>
  <script src="/static/web/desktop/theme.js"></script>
  <script src="/static/web/desktop.js"></script>
  <script src="/static/web/desktop/theme-fixture.js"></script>
</body>
</html>
"""

# 钉死平台暗色，使 system mode 的解析在测试机上是确定的；然后走真实控件 wiring：
# initThemeControl 绑定后点击「跟随系统」。
_THEME_FIXTURE_SCRIPT = """
const darkQuery = { matches: true, media: "(prefers-color-scheme: dark)", addEventListener() {}, removeEventListener() {} };
window.matchMedia = (query) => query === "(prefers-color-scheme: dark)"
  ? darkQuery
  : { matches: false, media: query, addEventListener() {}, removeEventListener() {} };
document.addEventListener("DOMContentLoaded", () => {
  document.querySelector('[data-theme-mode="system"]').click();
});
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

_THEME_PROBE = """
(() => {
  const theme = document.documentElement.getAttribute("data-theme");
  if (theme === "paper" || !theme) return undefined;
  return JSON.stringify({
    theme,
    storedTheme: localStorage.getItem("ui-theme-mode"),
    cookie: document.cookie,
    systemPressed: document.querySelector('[data-theme-mode="system"]').getAttribute("aria-pressed")
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
    def __init__(self, *, theme_fixture: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), _ConsumerHandler)
        self.requests: list[_ObservedRequest] = []
        self.theme_fixture = theme_fixture


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
            body = _THEME_HTML if server.theme_fixture else _CONSUMER_HTML
            self._send(200, body.encode(), "text/html; charset=utf-8")
            return
        if self.path == "/static/web/desktop-e2e-consumer.js":
            self._send(200, _CONSUMER_SCRIPT.encode(), "text/javascript; charset=utf-8")
            return
        if self.path == "/static/web/desktop/theme.js":
            self._send(200, _THEME_SCRIPT, "text/javascript; charset=utf-8")
            return
        if self.path == "/static/web/desktop.js":
            self._send(200, _DESKTOP_BOOT_SCRIPT, "text/javascript; charset=utf-8")
            return
        if self.path == "/static/web/desktop/theme-fixture.js":
            self._send(200, _THEME_FIXTURE_SCRIPT.encode(), "text/javascript; charset=utf-8")
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

@dataclass(frozen=True)
class _Controller:
    backend_origin: str

    def product_bridge_context(self) -> BridgeContext:
        return BridgeContext(backend_origin=self.backend_origin, app_token=_APP_TOKEN)

    def note_product_bridge_auth_failure(self, status_code: int, failed_token: str) -> bool:
        return False


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
    ]
    for request in consumer.requests:
        _assert_bridge_request(request, backend_origin)

    interaction = consumer.requests[-1]
    assert json.loads(interaction.body) == {"interaction": "primary"}
    for sensitive_header in ("x-control-token", "x-client-secret"):
        assert sensitive_header not in interaction.headers
    serialized = json.dumps([request.headers for request in consumer.requests], sort_keys=True)
    assert _CONTROL_TOKEN not in serialized
    assert _INSTANCE_SECRET not in serialized
    assert "browser-forged-token" not in serialized
    assert "browser-forged-bridge" not in serialized


def test_real_edge_theme_change_stays_in_the_browser(tmp_path: Path) -> None:
    """The exact production theme script persists locally without an API owner."""
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the Desktop theme bridge gate"
    consumer = _AuditedConsumerServer(theme_fixture=True)
    backend_origin = f"http://127.0.0.1:{consumer.server_address[1]}"
    manager = _manager(tmp_path, backend_origin)
    bootstrap_url = manager.prepare_web_bootstrap(tmp_path / "theme-bootstrap.html")

    with _serving(consumer), _serving(manager):
        value = evaluate_page(
            edge,
            profile=tmp_path / "edge-theme-bridge-profile",
            url=bootstrap_url,
            width=820,
            height=660,
            expression=_THEME_PROBE,
        )

    assert json.loads(value) == {
        "theme": "midnight",
        "storedTheme": "system",
        "cookie": "ui_theme=midnight",
        "systemPressed": "true",
    }
    observed = [(request.method, request.path) for request in consumer.requests]
    assert observed[0] == ("GET", "/web")
    # The static fetches race; order between them is not contractual.
    assert sorted(observed[1:]) == [
        ("GET", "/static/web/desktop.js"),
        ("GET", "/static/web/desktop/theme-fixture.js"),
        ("GET", "/static/web/desktop/theme.js"),
    ]


_REAL_RENDER_PROBE = """
(() => {
  const done = globalThis.__probeResult;
  if (done) return done;
  const atWeb = location.pathname === "/web" || location.pathname === "/web/pending";
  const ready = atWeb && document.querySelector("#main-content");
  if (!ready || globalThis.__probeStarted) return undefined;
  globalThis.__probeStarted = true;
  const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
  const snapshot = {
    overflow,
    ledgerChip: Boolean(document.querySelector(".ledger-role-chip")),
    hasOwnerLedger: document.body.innerText.includes("我的小票夹"),
    href: location.href,
    title: document.title
  };
  fetch("/web?ledger_id=tester_1", {credentials: "same-origin"})
    .then((response) => {
      globalThis.__probeResult = JSON.stringify({...snapshot, foreignStatus: response.status});
    })
    .catch((error) => {
      globalThis.__probeResult = JSON.stringify({...snapshot, foreignStatus: -1, error: String(error)});
    });
  return undefined;
})()
"""


@pytest.mark.parametrize(("width", "height"), [(1180, 760), (820, 660)])
def test_real_backend_bootstrap_pair_bridge_render_probe(
    tmp_path: Path,
    real_backend: RealBackend,
    width: int,
    height: int,
) -> None:
    """Full chain: pair through the manager, bootstrap, BFF-served /web render."""
    edge = discover_edge_executable()
    assert edge is not None, "Microsoft Edge is required for the real-backend render probe"
    stores = CredentialStores()
    controller = make_controller(real_backend.port, stores)
    manager = make_manager(controller)
    manager_origin = f"http://127.0.0.1:{manager.server_address[1]}"

    with _serving(manager):
        status, projection = manager_post_json(
            manager.server_address[1],
            "/api/product/pair",
            {"pairing_code": real_backend.fresh_pairing_code()},
            origin=manager_origin,
        )
        assert status == 200, projection
        assert projection["configured"] is True
        assert projection["ledger_id"] == real_backend.owner_ledger_id
        assert projection["role"] == "owner"
        assert "session_token" not in projection

        bootstrap_path = tmp_path / f"render-{width}x{height}" / "bootstrap.html"
        bootstrap_url = manager.prepare_web_bootstrap(bootstrap_path)
        assert _INSTANCE_SECRET not in bootstrap_url
        value = evaluate_page(
            edge,
            profile=tmp_path / f"edge-real-{width}x{height}",
            url=bootstrap_url,
            width=width,
            height=height,
            expression=_REAL_RENDER_PROBE,
        )

    assert not bootstrap_path.exists()
    assert isinstance(value, str)
    probe = json.loads(value)
    assert probe["overflow"] is False
    assert probe["ledgerChip"] is True
    assert probe["hasOwnerLedger"] is True
    # The server-side LedgerRequestGuard: a foreign ledger_id is refused.
    assert probe["foreignStatus"] == 403
    # Secret egress: the rendered URL never carries credentials.
    session = stores.sessions[E2E_INSTALLATION_ID]
    assert session.session_token not in probe["href"]
    assert _INSTANCE_SECRET not in probe["href"]
    assert session.session_token not in str(tmp_path / f"edge-real-{width}x{height}")


def test_real_backend_unpaired_bridge_renders_manager_recovery_action(
    tmp_path: Path,
    real_backend: RealBackend,
) -> None:
    stores = CredentialStores()
    manager = make_manager(make_controller(real_backend.port, stores))
    with _serving(manager):
        cookie = manager_bootstrap_cookies(manager, tmp_path / "unpaired-bootstrap.html")
        status, body = manager_get(manager, "/web", cookie)

    assert status == 401
    assert "桌面账本尚未绑定，请从系统管理完成绑定。" in body
    assert _INSTANCE_SECRET not in body


def test_real_backend_reconcile_after_manager_death_mid_pair(
    tmp_path: Path,
    real_backend: RealBackend,
) -> None:
    """Kill the 'manager' between pair-staging and activation; the recovery
    record lets a fresh controller replay the committed activation."""
    stores = CredentialStores()
    # Phase 1 of the ceremony happens, then the 'manager dies' before activate.
    pending = pair_product_session(
        real_backend.origin,
        real_backend.fresh_pairing_code(),
        timeout_seconds=5.0,
    )
    stores.recoveries[E2E_INSTALLATION_ID] = RebindRecovery(
        activation_attempt_id=pending.activation_attempt_id,
        activation_attempt_secret=pending.activation_attempt_secret,
        account_name=pending.session.account_name,
        ledger_id=pending.session.ledger_id,
        ledger_name=pending.session.ledger_name,
        device_name=pending.session.device_name,
        role=pending.session.role,
        activation_expires_at=pending.session.expires_at,
    )
    assert E2E_INSTALLATION_ID not in stores.sessions

    # A fresh controller instance reconciles: replay activate against the
    # real backend, promote the same derived value, keep fresh expiry.
    controller = make_controller(real_backend.port, stores)
    projection = controller.product_principal()

    assert projection["configured"] is True
    assert projection["ledger_id"] == real_backend.owner_ledger_id
    assert stores.recoveries == {}
    session = stores.sessions[E2E_INSTALLATION_ID]
    assert session.session_token == pending.session.session_token
    assert session.expires_at != pending.session.expires_at

    # And the promoted principal serves /web through the bridge.
    manager = make_manager(controller)
    with _serving(manager):
        cookie = manager_bootstrap_cookies(manager, tmp_path / "reconciled-bootstrap.html")
        status, body = manager_get(manager, "/web/pending", cookie)
    assert status == 200
    assert "我的小票夹" in body


def test_real_manager_window_close_reaps_edge_process(
    tmp_path: Path,
    real_backend: RealBackend,
) -> None:
    assert discover_edge_executable() is not None
    stores = CredentialStores()
    manager = make_manager(make_controller(real_backend.port, stores))
    with _serving(manager):
        bootstrap_path = tmp_path / "close-bootstrap.html"
        bootstrap_url = manager.prepare_web_bootstrap(bootstrap_path)
        assert _INSTANCE_SECRET not in bootstrap_url
        window = desktop_shell.open_app_window(
            bootstrap_url,
            profile=tmp_path / "edge-close-profile",
        )

        assert window is not None
        assert window.is_open()
        assert window.close(timeout=10) is True
        assert window.is_open() is False


def test_real_backend_switch_sequence_replacement_session_survives_cleanup(
    tmp_path: Path,
    real_backend: RealBackend,
) -> None:
    """P0 combination pin: pair → switch to another ledger (two-phase) → the
    cleanup revoke of the predecessor must leave the promoted successor
    usable — the /web surface keeps rendering the new ledger afterwards."""
    stores = CredentialStores()
    controller = make_controller(real_backend.port, stores)
    manager = make_manager(controller)
    manager_origin = f"http://127.0.0.1:{manager.server_address[1]}"

    with _serving(manager):
        status, projection = manager_post_json(
            manager.server_address[1],
            "/api/product/pair",
            {"pairing_code": real_backend.fresh_pairing_code()},
            origin=manager_origin,
        )
        assert status == 200, projection
        assert projection["ledger_id"] == real_backend.owner_ledger_id

        # A second ledger the paired account can switch to.
        request = urllib.request.Request(
            f"{real_backend.origin}/api/ledgers",
            data=json.dumps({"name": "切换目标账本"}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {real_backend.app_token}",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as resp:
            target = json.loads(resp.read())["ledger_id"]

        status, switched = manager_post_json(
            manager.server_address[1],
            "/api/product/ledger/switch",
            {"ledger_id": target},
            origin=manager_origin,
        )
        assert status == 200, switched
        assert switched["ledger_id"] == target
        assert switched["configured"] is True

        # The promoted successor survived the switch cleanup: /web renders
        # the new ledger through the bridge (a suicide would 401 here).
        cookie = manager_bootstrap_cookies(manager, tmp_path / "switch-bootstrap.html")
        status, body = manager_get(manager, "/web/pending", cookie)

    assert status == 200
    assert "切换目标账本" in body
