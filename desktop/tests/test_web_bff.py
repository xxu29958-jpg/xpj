"""Security matrix for the Manager same-origin Web BFF."""

from __future__ import annotations

import hashlib

import pytest

from backend_manager.web_bff import (
    SESSION_COOKIE,
    allowed_target,
    browser_session_valid,
    same_origin_request,
)


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("GET", "/web"),
        ("HEAD", "/web/confirmed?month=2026-07"),
        ("POST", "/web/expenses/new"),
        ("PUT", "/api/me/ui-preferences"),
        ("GET", "/static/web/product/shell.css"),
        ("HEAD", "/static/shared/tokens.css"),
    ],
)
def test_web_bff_allows_only_product_surface(method: str, target: str) -> None:
    assert allowed_target(target, method) is not None


@pytest.mark.parametrize(
    ("method", "target"),
    [
        ("GET", "/web/auth"),
        ("GET", "/web/auth/pair"),
        ("GET", "/owner"),
        ("GET", "/desktop"),
        ("GET", "/api/expenses"),
        ("GET", "/api/admin"),
        ("GET", "/api/me/ui-preferences"),
        ("POST", "/api/me/ui-preferences"),
        ("PUT", "/api/me/ui-preferences/"),
        ("PUT", "/api/me/ui-preferences?scope=desktop"),
        ("PUT", "/api/me/ui-preferences/extra"),
        ("GET", "/static/owner/app.css"),
        ("POST", "/static/web/app.js"),
        ("PUT", "/web/confirmed"),
        ("GET", "http://127.0.0.1/web"),
        ("GET", "//127.0.0.1/web"),
        ("GET", "/web/%2e%2e/api"),
        ("GET", "/web/%252e%252e/api"),
        ("GET", r"/web\..\api"),
        ("GET", "/web/%5c../api"),
    ],
)
def test_web_bff_rejects_privileged_and_ambiguous_targets(
    method: str,
    target: str,
) -> None:
    assert allowed_target(target, method) is None


def test_web_bff_session_and_same_origin_matrix() -> None:
    session_id = "high-entropy-process-session"
    session_digest = hashlib.sha256(session_id.encode("ascii")).hexdigest()
    origin = "http://127.0.0.1:8799"
    assert browser_session_valid(
        f"{SESSION_COOKIE}={session_id}; ui_theme=mono",
        (session_digest,),
    )
    assert not browser_session_valid(f"{SESSION_COOKIE}=wrong", (session_digest,))
    assert not browser_session_valid(f"{SESSION_COOKIE}=非ASCII", (session_digest,))
    assert same_origin_request(
        method="POST",
        origin=origin,
        referer=None,
        sec_fetch_site="same-origin",
        manager_origin=origin,
    )
    assert same_origin_request(
        method="PUT",
        origin=origin,
        referer=None,
        sec_fetch_site="same-origin",
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="POST",
        origin="https://attacker.invalid",
        referer=None,
        sec_fetch_site="cross-site",
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="POST",
        origin=None,
        referer=None,
        sec_fetch_site=None,
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="PUT",
        origin="https://attacker.invalid",
        referer=None,
        sec_fetch_site="cross-site",
        manager_origin=origin,
    )
    assert not same_origin_request(
        method="PUT",
        origin=None,
        referer=None,
        sec_fetch_site=None,
        manager_origin=origin,
    )


def test_relay_forwards_content_range_on_partial_responses() -> None:
    """A 206 partial is uninterpretable without Content-Range: it must pass."""
    import http.server
    import threading

    from backend_manager.web_bff import BridgeContext, relay

    class _PartialHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            body = b"partial-slice"
            self.send_response(206)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", "bytes 0-13/100")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PartialHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        response = relay(
            BridgeContext(
                backend_origin=f"http://127.0.0.1:{server.server_address[1]}",
                app_token="tbx-test",
            ),
            method="GET",
            raw_target="/web",
            client_headers={"Range": "bytes=0-13"},
            body=b"",
            manager_origin="http://127.0.0.1:8799",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status == 206
    headers = {name.casefold(): value for name, value in response.headers}
    assert headers["content-range"] == "bytes 0-13/100"
    assert headers["accept-ranges"] == "bytes"
    assert response.body == b"partial-slice"
