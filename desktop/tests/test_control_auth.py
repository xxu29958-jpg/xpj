"""Control-server authorization contract — the CSRF defenses, as a pure-function test."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend_manager.control_server import ControlServer, is_authorized, probe_existing_manager

_TOKEN = "s3cr3t-token"
_INSTANCE_SECRET = "instance-proof-secret"
_ORIGIN = "http://127.0.0.1:8799"


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
    assert _auth(
        provided_host="evil.test:8799",
        origin="http://evil.test:8799",
    ) is False


def test_token_alone_passes_when_fetch_metadata_absent() -> None:
    # Older clients / non-browser callers omit Sec-Fetch-Site and Origin; the
    # unguessable token still gates the request.
    assert _auth(sec_fetch_site=None, origin=None) is True


def test_host_and_origin_are_compared_as_canonical_tuples() -> None:
    assert _auth(provided_host=" 127.0.0.1:8799 ", origin=" HTTP://127.0.0.1:8799 ") is True
    assert _auth(
        provided_host="LOCALHOST",
        expected_host="localhost:80",
        origin="HTTP://LOCALHOST",
        expected_origin="http://localhost:80",
    ) is True


def test_canonicalization_does_not_accept_hostile_authorities() -> None:
    for hostile in ("127.0.0.1.evil:8799", "evil@127.0.0.1:8799", "127.0.0.1:8799.evil"):
        assert _auth(provided_host=hostile) is False
    assert _auth(origin="http://127.0.0.1.evil:8799") is False


def _assert_security_headers(response: http.client.HTTPResponse) -> None:
    assert response.getheader("Content-Security-Policy") == "frame-ancestors 'none'"
    assert response.getheader("X-Frame-Options") == "DENY"
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Referrer-Policy") == "no-referrer"


def test_control_server_never_serves_token_to_noncanonical_host(tmp_path) -> None:
    class Controller:
        def status(self) -> dict:
            return {"status": "ok"}

        def start(self) -> None: ...
        def stop(self) -> None: ...
        def restart(self) -> None: ...
        def auto_restart(self) -> None: ...
        def open_console(self) -> None: ...

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

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", f"/?instance={_INSTANCE_SECRET}")
        response = connection.getresponse()
        assert response.status == 200
        _assert_security_headers(response)
        assert _TOKEN.encode() in response.read()
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

        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        connection.request("GET", "/api/identity")
        response = connection.getresponse()
        assert response.status == 400
        _assert_security_headers(response)
        response.read()
        connection.close()
        assert probe_existing_manager(
            f"http://127.0.0.1:{server.server_address[1]}/",
            _INSTANCE_SECRET,
        ) is True
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
        assert probe_existing_manager(
            f"http://127.0.0.1:{server.server_address[1]}/",
            _INSTANCE_SECRET,
        ) is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
