"""Manager-to-backend Desktop bridge contracts."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend_manager.control_server import ControlServer
from backend_manager.product_data import (
    ProductDataError,
    activate_product_session,
    execute_inbox_command,
    fetch_product_workspace,
    list_product_ledgers,
    pair_product_session,
    revoke_product_session,
    switch_product_ledger,
)

_TOKEN = "desktop-control-token"
_INSTANCE = "desktop-instance-secret"


def _payload(workspace: str) -> dict:
    return {
        "workspace": workspace,
        "title": "收件",
        "ledger_id": "owner",
        "ledger_name": "我的小票夹",
        "role": "owner",
        "generated_at": "2026-07-18T08:00:00Z",
        "rows": [],
        "total_count": 0,
        "truncated": False,
        "empty_title": "已清空",
        "empty_detail": "没有记录",
        "ledgers": [],
    }


def test_gateway_fetches_only_the_allowlisted_loopback_projection() -> None:
    requests: list[tuple[str, str | None, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            requests.append(
                (
                    self.path,
                    self.headers.get("X-Ticketbox-Desktop-Bridge"),
                    self.headers.get("Authorization"),
                )
            )
            body = json.dumps(_payload("transactions")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        payload = fetch_product_workspace(
            f"http://127.0.0.1:{server.server_address[1]}",
            "transactions",
            "family ledger",
            "tbx-desktop-session",
            timeout_seconds=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert payload["workspace"] == "transactions"
    assert requests == [
        (
            "/desktop/workspaces/transactions?ledger_id=family+ledger",
            "v1",
            "Bearer tbx-desktop-session",
        )
    ]


def test_gateway_posts_exact_inbox_command_with_occ_and_idempotency() -> None:
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            requests.append(
                {
                    "path": self.path,
                    "bridge": self.headers.get("X-Ticketbox-Desktop-Bridge"),
                    "authorization": self.headers.get("Authorization"),
                    "idempotency": self.headers.get("Idempotency-Key"),
                    "payload": json.loads(self.rfile.read(length)),
                }
            )
            body = json.dumps(
                {
                    "action": "confirm",
                    "message": "收件已确认并进入流水。",
                    "expense_status": "confirmed",
                    "row_version": 3,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        response = execute_inbox_command(
            f"http://127.0.0.1:{server.server_address[1]}",
            "expense-public-id",
            "family ledger",
            {
                "action": "confirm",
                "expected_row_version": 2,
            },
            "desktop-idempotency-1",
            "tbx-desktop-session",
            timeout_seconds=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["expense_status"] == "confirmed"
    assert requests == [
        {
            "path": ("/desktop/workspaces/inbox/expenses/expense-public-id/commands?ledger_id=family+ledger"),
            "bridge": "v1",
            "authorization": "Bearer tbx-desktop-session",
            "idempotency": "desktop-idempotency-1",
            "payload": {
                "action": "confirm",
                "expected_row_version": 2,
            },
        }
    ]


def test_gateway_rejects_unknown_domains_and_non_loopback_origins() -> None:
    with pytest.raises(ProductDataError, match="未知的桌面工作区"):
        fetch_product_workspace(
            "http://127.0.0.1:8000",
            "library",
            None,
            "tbx-desktop-session",
            timeout_seconds=1,
        )
    with pytest.raises(ProductDataError, match="只能连接本机"):
        fetch_product_workspace(
            "https://api.example.test",
            "inbox",
            None,
            "tbx-desktop-session",
            timeout_seconds=1,
        )


def test_gateway_pairs_and_revokes_standard_desktop_app_session() -> None:
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "bridge": self.headers.get("X-Ticketbox-Desktop-Bridge"),
                    "body": json.loads(body) if body else None,
                }
            )
            if self.path == "/api/auth/pair":
                response = json.dumps(
                    {
                        "session_token": "tbx-paired-secret",
                        "account_name": "我",
                        "ledger_id": "owner",
                        "ledger_name": "我的小票夹",
                        "device_name": "小票夹 Desktop",
                        "role": "owner",
                        "expires_at": "2026-10-16T00:00:00Z",
                        "soft_refresh_after": "2026-10-09T00:00:00Z",
                        "activation_required": True,
                        "activation_expires_at": "2026-07-18T08:05:00Z",
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            if self.path == "/api/auth/desktop/activate":
                response = json.dumps(
                    {
                        "account_name": "我",
                        "ledger_id": "owner",
                        "ledger_name": "我的小票夹",
                        "device_name": "小票夹 Desktop",
                        "role": "owner",
                        "expires_at": "2026-10-16T00:00:00Z",
                        "soft_refresh_after": "2026-10-09T00:00:00Z",
                        "activation_required": False,
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        session = pair_product_session(
            origin,
            "12345678",
            timeout_seconds=1,
        )
        activated = activate_product_session(
            origin,
            session,
            "tbx-previous-secret",
            timeout_seconds=1,
        )
        revoke_product_session(
            origin,
            activated.session_token,
            timeout_seconds=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert session.ledger_id == "owner"
    assert session.role == "owner"
    assert requests == [
        {
            "path": "/api/auth/pair",
            "authorization": None,
            "bridge": None,
            "body": {
                "pairing_code": "12345678",
                "device_name": "小票夹 Desktop",
                "platform": "desktop",
            },
        },
        {
            "path": "/api/auth/desktop/activate",
            "authorization": "Bearer tbx-paired-secret",
            "bridge": "v1",
            "body": None,
        },
        {
            "path": "/desktop/session/revoke",
            "authorization": "Bearer tbx-paired-secret",
            "bridge": "v1",
            "body": None,
        },
    ]


def test_gateway_lists_memberships_and_rotates_to_viewer_ledger() -> None:
    requests: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.dumps(
                {
                    "ledgers": [
                        {
                            "ledger_id": "owner",
                            "name": "我的小票夹",
                            "role": "owner",
                            "is_default": True,
                            "created_at": None,
                            "archived_at": None,
                        },
                        {
                            "ledger_id": "family",
                            "name": "家庭账本",
                            "role": "viewer",
                            "is_default": False,
                            "created_at": None,
                            "archived_at": None,
                        },
                    ]
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.dumps(
                {
                    "session_token": "tbx-family-token",
                    "expires_at": "2026-10-16T00:00:00Z",
                    "soft_refresh_after": "2026-10-09T00:00:00Z",
                    "activation_required": True,
                    "activation_expires_at": "2026-07-18T08:05:00Z",
                    "ledger": {
                        "ledger_id": "family",
                        "name": "家庭账本",
                        "role": "viewer",
                        "is_default": False,
                        "created_at": None,
                        "archived_at": None,
                    },
                    "account_name": "我",
                    "device_name": "小票夹 Desktop",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        ledgers = list_product_ledgers(
            origin,
            "tbx-owner-token",
            timeout_seconds=1,
        )
        replacement = switch_product_ledger(
            origin,
            "family",
            "tbx-owner-token",
            timeout_seconds=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert ledgers[1] == {
        "ledger_id": "family",
        "name": "家庭账本",
        "role": "viewer",
        "is_default": False,
    }
    assert replacement.ledger_id == "family"
    assert replacement.role == "viewer"
    assert replacement.session_token == "tbx-family-token"
    assert requests == [
        ("/api/ledgers", "Bearer tbx-owner-token"),
        ("/api/ledgers/family/switch/prepare", "Bearer tbx-owner-token"),
    ]


def test_control_server_product_endpoint_requires_token_and_validates_query(tmp_path) -> None:
    calls: list[tuple[str, str | None]] = []

    class Controller:
        def status(self) -> dict:
            return {"status": "ok"}

        def product_workspace(self, workspace: str, ledger_id: str | None = None) -> dict:
            calls.append((workspace, ledger_id))
            return _payload(workspace)

        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE,
        ui_html=ui,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/product/inbox")
        denied = connection.getresponse()
        assert denied.status == 403
        denied.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "GET",
            "/api/product/inbox?ledger_id=family",
            headers={"X-Control-Token": _TOKEN},
        )
        accepted = connection.getresponse()
        assert accepted.status == 200
        assert json.loads(accepted.read())["workspace"] == "inbox"
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "GET",
            "/api/product/inbox?ledger_id=family&extra=1",
            headers={"X-Control-Token": _TOKEN},
        )
        invalid = connection.getresponse()
        assert invalid.status == 400
        assert json.loads(invalid.read()) == {"error": "invalid_request"}
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert calls == [("inbox", "family")]


def test_control_server_inbox_command_is_same_origin_and_forwards_contract(tmp_path) -> None:
    calls: list[tuple[str, str | None, dict, str]] = []

    class Controller:
        def product_inbox_command(
            self,
            public_id: str,
            ledger_id: str | None,
            payload: dict,
            idempotency_key: str,
        ) -> dict:
            calls.append((public_id, ledger_id, payload, idempotency_key))
            return {
                "action": payload["action"],
                "message": "操作完成",
                "expense_status": "pending",
                "row_version": 2,
            }

        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE,
        ui_html=ui,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    path = "/api/product/inbox/expenses/expense-1/commands?ledger_id=owner"
    body = json.dumps(
        {
            "action": "save",
            "expected_row_version": 1,
            "merchant": "修正商家",
        }
    )
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "desktop-save-1",
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        denied = connection.getresponse()
        assert denied.status == 403
        denied.read()
        connection.close()

        origin = f"http://127.0.0.1:{port}"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Control-Token": _TOKEN,
                "Idempotency-Key": "desktop-save-1",
                "Origin": origin,
                "Sec-Fetch-Site": "same-origin",
            },
        )
        accepted = connection.getresponse()
        assert accepted.status == 200
        assert json.loads(accepted.read())["row_version"] == 2
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert calls == [
        (
            "expense-1",
            "owner",
            {
                "action": "save",
                "expected_row_version": 1,
                "merchant": "修正商家",
            },
            "desktop-save-1",
        )
    ]


def test_control_server_pairs_reports_and_unpairs_without_exposing_token(tmp_path) -> None:
    calls: list[tuple[str, str | None]] = []

    class Controller:
        def product_principal(self) -> dict:
            calls.append(("status", None))
            return {
                "configured": True,
                "account_name": "我",
                "ledger_id": "owner",
                "ledger_name": "我的小票夹",
                "device_name": "小票夹 Desktop",
                "role": "owner",
                "expires_at": None,
            }

        def pair_product_principal(self, pairing_code: str) -> dict:
            calls.append(("pair", pairing_code))
            return self.product_principal()

        def switch_product_principal_ledger(self, ledger_id: str) -> dict:
            calls.append(("switch", ledger_id))
            return {
                "configured": True,
                "account_name": "我",
                "ledger_id": ledger_id,
                "ledger_name": "家庭账本",
                "device_name": "小票夹 Desktop",
                "role": "viewer",
                "expires_at": None,
            }

        def unpair_product_principal(self) -> dict:
            calls.append(("unpair", None))
            return {"configured": False}

        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE,
        ui_html=ui,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    authorized = {
        "X-Control-Token": _TOKEN,
        "Origin": origin,
        "Sec-Fetch-Site": "same-origin",
    }
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/api/product/pair",
            body=json.dumps({"pairing_code": "12345678"}),
            headers={
                **authorized,
                "Content-Type": "application/json",
            },
        )
        paired = connection.getresponse()
        assert paired.status == 200
        paired_payload = json.loads(paired.read())
        assert paired_payload["configured"] is True
        assert "session_token" not in paired_payload
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "GET",
            "/api/product/session",
            headers={"X-Control-Token": _TOKEN},
        )
        session = connection.getresponse()
        assert session.status == 200
        session_payload = json.loads(session.read())
        assert session_payload["ledger_id"] == "owner"
        assert "session_token" not in session_payload
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/api/product/ledger/switch",
            body=json.dumps({"ledger_id": "family"}),
            headers={
                **authorized,
                "Content-Type": "application/json",
            },
        )
        switched = connection.getresponse()
        assert switched.status == 200
        switched_payload = json.loads(switched.read())
        assert switched_payload["ledger_id"] == "family"
        assert switched_payload["role"] == "viewer"
        assert "session_token" not in switched_payload
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/api/product/unpair",
            body="",
            headers=authorized,
        )
        unpaired = connection.getresponse()
        assert unpaired.status == 200
        assert json.loads(unpaired.read()) == {"configured": False}
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert calls == [
        ("pair", "12345678"),
        ("status", None),
        ("status", None),
        ("switch", "family"),
        ("unpair", None),
    ]


def test_control_server_serves_modular_product_assets_under_strict_csp(tmp_path) -> None:
    class Controller:
        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    product = tmp_path / "product.html"
    css = tmp_path / "product.css"
    javascript = tmp_path / "product.js"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    product.write_text(
        '<meta name="ticketbox-control-token" content="__CONTROL_TOKEN__">'
        '<link rel="stylesheet" href="/product.css">'
        '<script src="/product.js" defer></script>',
        encoding="utf-8",
    )
    css.write_text(":root { color-scheme: light; }", encoding="utf-8")
    javascript.write_text("document.documentElement.dataset.ready = '1';", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE,
        ui_html=ui,
        product_html=product,
        product_css=css,
        product_js=javascript,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    port = server.server_address[1]
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", f"/app?instance={_INSTANCE}")
        page = connection.getresponse()
        assert page.status == 404
        assert page.headers.get_all("Set-Cookie") is None
        assert _TOKEN not in page.read().decode()
        connection.close()

        for path, content_type, expected in (
            ("/product.css", "text/css; charset=utf-8", "color-scheme"),
            ("/product.js", "text/javascript; charset=utf-8", "dataset.ready"),
        ):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("GET", path)
            asset = connection.getresponse()
            assert asset.status == 200
            assert asset.getheader("Content-Type") == content_type
            assert expected in asset.read().decode()
            connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
