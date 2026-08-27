"""Control-server authorization contract — the CSRF defenses, as a pure-function test."""

from __future__ import annotations

import http.client
import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend_manager.app_controller import AppController
from backend_manager.control_server import (
    ControlServer,
    is_authorized,
    probe_existing_manager,
    request_existing_manager_window,
)
from backend_manager.projection import UnavailableInstalledRuntimeConfigProvider

_TOKEN = "s3cr3t-token"
_INSTANCE_SECRET = "instance-proof-secret"
_ORIGIN = "http://127.0.0.1:8799"
_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


def _auth(**overrides: object) -> bool:
    kwargs: dict = {
        "token": _TOKEN,
        "provided_token": _TOKEN,
        "sec_fetch_site": "same-origin",
        "origin": _ORIGIN,
        "expected_origin": _ORIGIN,
        "provided_host": "127.0.0.1:8799",
        "expected_host": "127.0.0.1:8799",
    }
    kwargs.update(overrides)
    return is_authorized(**kwargs)  # type: ignore[arg-type]


def test_valid_token_same_origin_is_allowed() -> None:
    assert _auth() is True


def test_missing_token_is_rejected() -> None:
    assert _auth(provided_token=None) is False


def test_wrong_token_is_rejected() -> None:
    assert _auth(provided_token="nope") is False


def test_cross_site_fetch_is_rejected() -> None:
    # A malicious page's request carries Sec-Fetch-Site: cross-site.
    assert _auth(sec_fetch_site="cross-site") is False


def test_foreign_origin_is_rejected() -> None:
    assert _auth(origin="https://evil.example") is False


def test_foreign_host_is_rejected_even_when_origin_matches_it() -> None:
    assert (
        _auth(
            provided_host="evil.test:8799",
            origin="http://evil.test:8799",
        )
        is False
    )


def test_token_alone_passes_when_fetch_metadata_absent() -> None:
    # Older clients / non-browser callers omit Sec-Fetch-Site and Origin; the
    # unguessable token still gates the request.
    assert _auth(sec_fetch_site=None, origin=None) is True


def test_host_and_origin_are_compared_as_canonical_tuples() -> None:
    assert _auth(provided_host=" 127.0.0.1:8799 ", origin=" HTTP://127.0.0.1:8799 ") is True
    assert (
        _auth(
            provided_host="LOCALHOST",
            expected_host="localhost:80",
            origin="HTTP://LOCALHOST",
            expected_origin="http://localhost:80",
        )
        is True
    )


def test_canonicalization_does_not_accept_hostile_authorities() -> None:
    for hostile in ("127.0.0.1.evil:8799", "evil@127.0.0.1:8799", "127.0.0.1:8799.evil"):
        assert _auth(provided_host=hostile) is False
    assert _auth(origin="http://127.0.0.1.evil:8799") is False


def _assert_security_headers(response: http.client.HTTPResponse) -> None:
    assert response.getheader("Content-Security-Policy") == _CONTENT_SECURITY_POLICY
    assert response.getheader("X-Frame-Options") == "DENY"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Referrer-Policy") == "no-referrer"


def test_control_server_never_serves_token_to_noncanonical_host(tmp_path) -> None:
    reopened: list[str] = []

    class Controller:
        def status(self) -> dict:
            return {"status": "ok"}

        def start(self) -> None: ...
        def stop(self) -> None: ...
        def restart(self) -> None: ...
        def auto_restart(self) -> None: ...
        def open_console(self) -> None: ...
        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
        request_window=lambda: (reopened.append("window"), True)[-1],
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.putrequest("GET", "/", skip_host=True)
        connection.putheader("Host", f"evil.test:{server.server_address[1]}")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 421
        _assert_security_headers(response)
        assert _TOKEN.encode() not in response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 403
        _assert_security_headers(response)
        assert _TOKEN.encode() not in response.read()
        connection.close()

        # The instance-secret URL flow is deleted: secrets never travel in URLs.
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", f"/?instance={_INSTANCE_SECRET}")
        response = connection.getresponse()
        assert response.status == 404
        assert _TOKEN.encode() not in response.read()
        connection.close()

        # The bootstrap flow replaces it: ACL'd single-use HTML -> POST ->
        # 4 HttpOnly path-scoped cookies -> manager page with the control token.
        bootstrap_path = tmp_path / "bootstrap.html"
        bootstrap_url = server.prepare_web_bootstrap(bootstrap_path)
        assert _INSTANCE_SECRET not in bootstrap_url
        assert _INSTANCE_SECRET not in str(bootstrap_path)
        bootstrap_html = bootstrap_path.read_text(encoding="utf-8")
        assert _INSTANCE_SECRET not in bootstrap_html
        match = re.search(r'name="bootstrap_token" value="([^"]+)"', bootstrap_html)
        assert match is not None
        bootstrap_body = urllib.parse.urlencode({"bootstrap_token": match.group(1)}).encode()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "POST",
            "/api/bootstrap",
            body=bootstrap_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        assert response.status == 200
        cookies = response.headers.get_all("Set-Cookie")
        assert cookies is not None and len(cookies) == 4
        assert any("Path=/web" in cookie for cookie in cookies)
        assert any("Path=/static" in cookie for cookie in cookies)
        assert any("Path=/api/me/ui-preferences" in cookie for cookie in cookies)
        assert any("ticketbox_manager_control=" in cookie and "Path=/" in cookie for cookie in cookies)
        assert all("HttpOnly" in cookie for cookie in cookies)
        assert all("SameSite=Strict" in cookie for cookie in cookies)
        session_ids = [cookie.partition(";")[0].partition("=")[2] for cookie in cookies]
        assert len(set(session_ids)) == 4
        assert all(session_id not in repr(server._web_session_digests) for session_id in session_ids)
        assert _TOKEN.encode() not in response.read()
        connection.close()
        assert not bootstrap_path.exists()

        cookie_header = "; ".join(cookie.partition(";")[0] for cookie in cookies)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/", headers={"Cookie": cookie_header})
        response = connection.getresponse()
        assert response.status == 200
        assert _TOKEN.encode() in response.read()
        connection.close()

        # Single-use: the replay is 410, a foreign token is 401, a cancelled
        # grant is 410 too.
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "POST",
            "/api/bootstrap",
            body=bootstrap_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        assert response.status == 410
        response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "POST",
            "/api/bootstrap",
            body=urllib.parse.urlencode({"bootstrap_token": "invalid-bootstrap-token"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        assert response.status == 401
        response.read()
        connection.close()

        cancelled_path = tmp_path / "cancelled-bootstrap.html"
        server.prepare_web_bootstrap(cancelled_path)
        cancelled_match = re.search(
            r'name="bootstrap_token" value="([^"]+)"',
            cancelled_path.read_text(encoding="utf-8"),
        )
        assert cancelled_match is not None
        cancelled_body = urllib.parse.urlencode({"bootstrap_token": cancelled_match.group(1)}).encode()
        server.cancel_web_bootstrap(cancelled_path)
        assert not cancelled_path.exists()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request(
            "POST",
            "/api/bootstrap",
            body=cancelled_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        assert response.status == 410
        response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/api/status")
        response = connection.getresponse()
        assert response.status == 403
        assert _TOKEN.encode() not in response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/api/status", headers={"X-Control-Token": _TOKEN})
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ok"}
        connection.close()

        action_headers = {
            "X-Control-Token": _TOKEN,
            "Sec-Fetch-Site": "same-origin",
            "Origin": f"http://127.0.0.1:{server.server_address[1]}",
        }
        for invalid_path in ("/anything/start", "/api/start?unexpected=1"):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
            connection.request("POST", invalid_path, headers=action_headers)
            response = connection.getresponse()
            assert response.status == 404
            response.read()
            connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("POST", "/api/start", body=b"{}", headers=action_headers)
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/api/identity")
        response = connection.getresponse()
        assert response.status == 400
        _assert_security_headers(response)
        response.read()
        connection.close()
        assert (
            probe_existing_manager(
                f"http://127.0.0.1:{server.server_address[1]}/",
                _INSTANCE_SECRET,
            )
            is True
        )
        assert (
            request_existing_manager_window(
                f"http://127.0.0.1:{server.server_address[1]}/",
                _INSTANCE_SECRET,
            )
            is True
        )
        assert reopened == ["window"]

        browser_reopen = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_address[1],
            timeout=2,
        )
        browser_reopen.request(
            "POST",
            "/api/reopen",
            headers={
                "X-Ticketbox-Reopen-Challenge": "x" * 43,
                "Origin": f"http://127.0.0.1:{server.server_address[1]}",
            },
        )
        browser_response = browser_reopen.getresponse()
        assert browser_response.status == 403
        browser_response.read()
        browser_reopen.close()
        assert reopened == ["window"]

        native_reopen = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_address[1],
            timeout=2,
        )
        native_reopen.request(
            "POST",
            "/api/reopen",
            headers={
                "X-Ticketbox-Reopen-Challenge": "x" * 43,
                "X-Ticketbox-Reopen-Proof": "0" * 64,
            },
        )
        native_response = native_reopen.getresponse()
        assert native_response.status == 403
        native_response.read()
        native_reopen.close()
        assert reopened == ["window"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_fake_fixed_identity_listener_cannot_prove_manager_ownership() -> None:
    class FakeIdentityHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            body = json.dumps({"product": "ticketbox-desktop-manager", "protocol": "v1"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeIdentityHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        assert (
            probe_existing_manager(
                f"http://127.0.0.1:{server.server_address[1]}/",
                _INSTANCE_SECRET,
            )
            is False
        )
        assert (
            request_existing_manager_window(
                f"http://127.0.0.1:{server.server_address[1]}/",
                _INSTANCE_SECRET,
            )
            is False
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_control_server_rejects_overlapping_actions_but_keeps_status_available(tmp_path) -> None:
    action_entered = threading.Event()
    release_action = threading.Event()

    class BlockingController:
        def status(self) -> dict:
            return {"status": "ok"}

        def start(self) -> None:
            action_entered.set()
            assert release_action.wait(timeout=2)

        def stop(self) -> None: ...
        def restart(self) -> None: ...
        def auto_restart(self) -> None: ...
        def open_console(self) -> None: ...
        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=BlockingController(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    headers = {
        "X-Control-Token": _TOKEN,
        "Sec-Fetch-Site": "same-origin",
        "Origin": origin,
    }
    server_thread = threading.Thread(target=server.serve_forever)
    first_result: list[tuple[int, dict]] = []

    def run_first_action() -> None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request("POST", "/api/start", headers=headers)
        response = connection.getresponse()
        first_result.append((response.status, json.loads(response.read())))
        connection.close()

    server_thread.start()
    action_thread = threading.Thread(target=run_first_action)
    action_thread.start()
    try:
        assert action_entered.wait(timeout=1)

        status_connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        status_connection.request("GET", "/api/status", headers={"X-Control-Token": _TOKEN})
        status_response = status_connection.getresponse()
        assert status_response.status == 200
        assert json.loads(status_response.read()) == {"status": "ok"}
        status_connection.close()

        overlap = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        overlap.request("POST", "/api/start", headers=headers)
        overlap_response = overlap.getresponse()
        assert overlap_response.status == 409
        assert json.loads(overlap_response.read()) == {"error": "operation_in_progress"}
        overlap.close()
    finally:
        release_action.set()
        action_thread.join(timeout=3)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert first_result == [(200, {"status": "ok"})]


def test_unqualified_data_lifecycle_endpoints_are_not_exposed(tmp_path) -> None:
    calls: list[str] = []

    class Controller:
        def status(self) -> dict[str, str]:
            return {"status": "ok"}

        def backup(self) -> None:
            calls.append("backup")

        def backup_inventory(self) -> list[dict[str, object]]:
            calls.append("backups")
            return []

        def restore(self, _backup_generation: str) -> None:
            calls.append("restore")

        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )
    port = server.server_address[1]
    headers = {
        "X-Control-Token": _TOKEN,
        "Sec-Fetch-Site": "same-origin",
        "Origin": f"http://127.0.0.1:{port}",
    }
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        for path, body in (
            ("/api/backup", None),
            ("/api/backups", None),
            (
                "/api/restore",
                json.dumps(
                    {"backup_generation": "ticketbox-backup-11111111-1111-4111-8111-111111111111"}
                ),
            ),
        ):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            assert response.status == 404
            response.read()
            connection.close()
        assert calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_control_server_rejects_every_action_and_reopen_after_shutdown_seal(tmp_path) -> None:
    controller = AppController(UnavailableInstalledRuntimeConfigProvider(), maintenance_version="1.2.0")
    controller.request_manager_shutdown()
    reopened: list[str] = []
    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=controller,
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
        request_window=lambda: (reopened.append("window"), True)[-1],
    )
    port = server.server_address[1]
    headers = {
        "X-Control-Token": _TOKEN,
        "Sec-Fetch-Site": "same-origin",
        "Origin": f"http://127.0.0.1:{port}",
    }
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()
    try:
        for action in (
            "start",
            "stop",
            "restart",
            "auto_restart",
            "open_console",
            "open_pairing",
            "open_devices",
            "open_upload_links",
            "open_backups",
            "open_diagnostics",
            "open_settings",
            "export_diagnostics",
        ):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("POST", f"/api/{action}", headers=headers)
            response = connection.getresponse()
            assert response.status == 409
            assert json.loads(response.read()) == {"error": "manager_shutting_down"}
            connection.close()

        assert request_existing_manager_window(f"http://127.0.0.1:{port}/", _INSTANCE_SECRET) is False
        assert reopened == []
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_control_server_product_endpoints_stay_manager_plane(tmp_path) -> None:
    calls: list[tuple[str, str | None]] = []

    class Controller:
        def product_principal(self) -> dict:
            calls.append(("session", None))
            return {
                "configured": True,
                "account_name": "我",
                "ledger_id": "owner",
                "ledger_name": "我的小票夹",
                "device_name": "小票夹 Desktop",
                "role": "owner",
                "expires_at": None,
            }

        def product_ledgers(self) -> list[dict]:
            calls.append(("ledgers", None))
            return [
                {
                    "ledger_id": "owner",
                    "name": "我的小票夹",
                    "role": "owner",
                    "is_default": True,
                    "is_current": True,
                },
                {
                    "ledger_id": "family",
                    "name": "家庭账本",
                    "role": "viewer",
                    "is_default": False,
                    "is_current": False,
                },
            ]

        def pair_product_principal(self, pairing_code: str) -> dict:
            calls.append(("pair", pairing_code))
            return self.product_principal()

        def switch_product_principal_ledger(self, ledger_id: str) -> dict:
            calls.append(("switch", ledger_id))
            return {"configured": True, "ledger_id": ledger_id}

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
        instance_secret=_INSTANCE_SECRET,
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
        # Session + ledgers are token-gated reads; pairing state never leaks a token.
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/product/session")
        denied = connection.getresponse()
        assert denied.status == 403
        denied.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/product/session", headers={"X-Control-Token": _TOKEN})
        session = connection.getresponse()
        assert session.status == 200
        session_payload = json.loads(session.read())
        assert session_payload["ledger_id"] == "owner"
        assert "session_token" not in session_payload
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/product/ledgers", headers={"X-Control-Token": _TOKEN})
        ledgers = connection.getresponse()
        assert ledgers.status == 200
        ledgers_payload = json.loads(ledgers.read())
        assert ledgers_payload["ledgers"][1] == {
            "ledger_id": "family",
            "name": "家庭账本",
            "role": "viewer",
            "is_default": False,
            "is_current": False,
        }
        connection.close()

        # Mutations need the full same-origin authorization.
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/api/product/pair",
            body=json.dumps({"pairing_code": "12345678"}),
            headers={"Content-Type": "application/json"},
        )
        denied_pair = connection.getresponse()
        assert denied_pair.status == 403
        denied_pair.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/api/product/pair",
            body=json.dumps({"pairing_code": "12345678"}),
            headers={**authorized, "Content-Type": "application/json"},
        )
        paired = connection.getresponse()
        assert paired.status == 200
        paired_payload = json.loads(paired.read())
        assert paired_payload["configured"] is True
        assert "session_token" not in paired_payload
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/api/product/ledger/switch",
            body=json.dumps({"ledger_id": "family"}),
            headers={**authorized, "Content-Type": "application/json"},
        )
        switched = connection.getresponse()
        assert switched.status == 200
        assert json.loads(switched.read())["ledger_id"] == "family"
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
        ("session", None),
        ("ledgers", None),
        ("pair", "12345678"),
        ("session", None),
        ("switch", "family"),
        ("unpair", None),
    ]


def _bootstrap_cookie_header(server: ControlServer, tmp_path) -> str:
    import re as _re
    import urllib.parse as _urlparse

    bootstrap_path = tmp_path / "bootstrap.html"
    server.prepare_web_bootstrap(bootstrap_path)
    document = bootstrap_path.read_text(encoding="utf-8")
    match = _re.search(r'name="bootstrap_token" value="([^"]+)"', document)
    assert match is not None
    body = _urlparse.urlencode({"bootstrap_token": match.group(1)}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
    connection.request(
        "POST",
        "/api/bootstrap",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = connection.getresponse()
    assert response.status == 200
    cookies = response.headers.get_all("Set-Cookie")
    response.read()
    connection.close()
    assert cookies is not None
    return "; ".join(cookie.partition(";")[0] for cookie in cookies)


def test_unpaired_bootstrap_recovery_page_routes_back_to_manager(tmp_path) -> None:
    """P1-1: bootstrap lands on /web, but the address-bar-less window must
    still reach the manager UI: the recovery page carries the way back."""

    from backend_manager.product_data import ProductDataError

    class Controller:
        def product_bridge_context(self):
            raise ProductDataError(
                "请先使用 8 位绑定码连接桌面账本。",
                error="product_principal_required",
                status_code=401,
            )

        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        cookie = _bootstrap_cookie_header(server, tmp_path)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/web", headers={"Cookie": cookie})
        recovery = connection.getresponse()
        assert recovery.status == 401
        body = recovery.read().decode()
        assert "桌面账本尚未绑定，请从系统管理完成绑定。" in body
        assert 'href="/"' in body
        connection.close()

        # The same bootstrap's control cookie opens the manager page itself.
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/", headers={"Cookie": cookie})
        manager_page = connection.getresponse()
        assert manager_page.status == 200
        assert _TOKEN.encode() in manager_page.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_bridged_401_clears_stored_credential_and_returns_pairing_state(tmp_path) -> None:
    """P1-3: a backend 401 through the bridge retires the dead WinCred entry."""
    from backend_manager.app_controller import AppController
    from backend_manager.config import ManagerConfig, SourceRuntimeConfig
    from backend_manager.product_identity import ProductSession
    from backend_manager.runtime import RuntimeStatus

    class _HealthyRuntime:
        def status(self) -> RuntimeStatus:
            return RuntimeStatus(
                mode="source",
                running=True,
                healthy=True,
                pid=None,
                uptime_seconds=1,
                auto_restart=True,
                auto_restart_configurable=True,
                restarts=0,
                backend_service_state=None,
                database_service_state=None,
                log=["ready"],
                health_state="healthy",
                health_detail="identity verified",
                runtime_access_state="available",
                owner_state="configured",
            )

    class _DeadBackend(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            body = b'{"error":"invalid_token","message":"dead"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    backend = ThreadingHTTPServer(("127.0.0.1", 0), _DeadBackend)
    backend_thread = threading.Thread(target=backend.serve_forever)
    backend_thread.start()

    installation_id = "ticketbox-0123456789abcdef0123456789abcdef"
    sessions = {
        installation_id: ProductSession(
            session_token="tbx-dead-desktop-token",
            account_name="我",
            ledger_id="owner",
            ledger_name="我的小票夹",
            device_name="小票夹 Desktop",
            role="owner",
            expires_at=None,
        )
    }
    recoveries: dict = {}
    config = ManagerConfig(
        runtime=SourceRuntimeConfig(tmp_path / "backend", tmp_path / "python.exe", tmp_path / "backend"),
        backend_host="127.0.0.1",
        backend_port=backend.server_address[1],
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=None,
        expected_installation_id=installation_id,
        health_request_timeout_seconds=1.0,
    )
    controller = AppController(
        _HealthyRuntime(),
        config,
        product_session_loader=sessions.get,
        product_session_saver=sessions.__setitem__,
        product_session_deleter=lambda key: sessions.pop(key, None),
        product_recovery_loader=recoveries.get,
        product_recovery_saver=recoveries.__setitem__,
        product_recovery_deleter=lambda key: recoveries.pop(key, None),
    )

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=controller,
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        cookie = _bootstrap_cookie_header(server, tmp_path)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/web", headers={"Cookie": cookie})
        recovery = connection.getresponse()
        assert recovery.status == 401
        body = recovery.read().decode()
        assert "桌面身份已失效，请从系统管理重新绑定。" in body
        assert 'href="/"' in body
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=2)

    # The dead credential was retired BEFORE the recovery state rendered.
    assert sessions == {}
    assert controller.product_principal() == {"configured": False}


def test_stale_bootstrap_material_is_replaced_not_crash_looping(tmp_path) -> None:
    """P2-1: a manager killed mid-launch leaves O_EXCL material behind."""

    class Controller:
        def is_manager_shutting_down(self) -> bool:
            return False

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )
    try:
        stale = tmp_path / "edge-session" / "window-0001" / "bootstrap.html"
        stale.parent.mkdir(parents=True)
        stale.write_text("<!doctype html><title>stale</title>", encoding="utf-8")

        url = server.prepare_web_bootstrap(stale)

        assert url == stale.as_uri()
        document = stale.read_text(encoding="utf-8")
        assert "stale" not in document
        assert 'name="bootstrap_token"' in document
    finally:
        server.server_close()
    assert not stale.exists()


def test_owner_links_hand_off_to_manager_actions_not_404(tmp_path) -> None:
    """P2-3: /owner/* clicks in the product window invoke manager open_*."""
    opened: list[str] = []

    class Controller:
        def is_manager_shutting_down(self) -> bool:
            return False

        def open_pairing(self) -> None:
            opened.append("open_pairing")

    ui = tmp_path / "ui.html"
    ui.write_text("token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        cookie = _bootstrap_cookie_header(server, tmp_path)

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/owner/pairing")
        denied = connection.getresponse()
        assert denied.status == 403
        denied.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/owner/pairing", headers={"Cookie": cookie})
        handed_off = connection.getresponse()
        assert handed_off.status == 200
        body = handed_off.read().decode()
        assert "已在本机默认浏览器打开系统管理页面" in body
        assert 'href="/web"' in body
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/owner/unknown", headers={"Cookie": cookie})
        unknown = connection.getresponse()
        assert unknown.status == 404
        unknown.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert opened == ["open_pairing"]
