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
_PRODUCT_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
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


def _assert_security_headers(
    response: http.client.HTTPResponse,
    *,
    content_security_policy: str = _CONTENT_SECURITY_POLICY,
) -> None:
    assert response.getheader("Content-Security-Policy") == content_security_policy
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
    product = tmp_path / "product.html"
    product.write_text("product-token=__CONTROL_TOKEN__", encoding="utf-8")
    server = ControlServer(
        "127.0.0.1",
        0,
        controller=Controller(),
        token=_TOKEN,
        instance_secret=_INSTANCE_SECRET,
        ui_html=ui,
        product_html=product,
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
        connection.request("GET", "/app")
        response = connection.getresponse()
        assert response.status == 404
        _assert_security_headers(
            response,
            content_security_policy=_PRODUCT_CONTENT_SECURITY_POLICY,
        )
        assert _TOKEN.encode() not in response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 403
        _assert_security_headers(response)
        assert _TOKEN.encode() not in response.read()
        connection.close()

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", f"/?instance={_INSTANCE_SECRET}")
        response = connection.getresponse()
        assert response.status == 404
        _assert_security_headers(response)
        assert _TOKEN.encode() not in response.read()
        connection.close()

        bootstrap_path = tmp_path / "bootstrap.html"
        bootstrap_url = server.prepare_web_bootstrap(bootstrap_path)
        assert _INSTANCE_SECRET not in bootstrap_url
        assert _INSTANCE_SECRET not in str(bootstrap_path)
        bootstrap_html = bootstrap_path.read_text(encoding="utf-8")
        assert _INSTANCE_SECRET not in bootstrap_html
        match = re.search(r'name="bootstrap_token" value="([^"]+)"', bootstrap_html)
        assert match is not None
        bootstrap_token = match.group(1)
        bootstrap_body = urllib.parse.urlencode(
            {"bootstrap_token": bootstrap_token}
        ).encode()

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
        assert any("Path=/web" in cookie for cookie in cookies)
        assert any("Path=/static" in cookie for cookie in cookies)
        assert any("ticketbox_manager_control=" in cookie for cookie in cookies)
        assert all("HttpOnly" in cookie for cookie in cookies)
        assert all("SameSite=Strict" in cookie for cookie in cookies)
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
        invalid_body = urllib.parse.urlencode(
            {"bootstrap_token": "invalid-bootstrap-token"}
        ).encode()
        connection.request(
            "POST",
            "/api/bootstrap",
            body=invalid_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        assert response.status == 401
        response.read()
        connection.close()

        cancelled_path = tmp_path / "cancelled-bootstrap.html"
        server.prepare_web_bootstrap(cancelled_path)
        cancelled_html = cancelled_path.read_text(encoding="utf-8")
        cancelled_match = re.search(
            r'name="bootstrap_token" value="([^"]+)"',
            cancelled_html,
        )
        assert cancelled_match is not None
        cancelled_body = urllib.parse.urlencode(
            {"bootstrap_token": cancelled_match.group(1)}
        ).encode()
        server.cancel_web_bootstrap(cancelled_path)
        assert not cancelled_path.exists()

        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.server_address[1],
            timeout=2,
        )
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
        connection.request("GET", f"/app?instance={_INSTANCE_SECRET}")
        response = connection.getresponse()
        assert response.status == 404
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
