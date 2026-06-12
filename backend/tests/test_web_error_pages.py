"""Browser-friendly HTML error pages for /web and /owner (A3 fallback).

The high-traffic /web write paths already flash-redirect on error (batches
#37 / #44 / #47). This covers the *bottom* layer added in :mod:`app.errors`:
a browser that lands on a /web or /owner URL with no matching route (404) or
hits an uncaught 500 gets a minimal themed HTML page instead of the raw JSON
envelope. Everything else — /api, /u, Android (OkHttp sends no Accept header
by default, so it lands in the no-Accept bucket), shortcuts — keeps the
byte-identical JSON envelope (ENGINEERING_RULES §4; the Android ErrorResponse
decoder must never see HTML).

Two test layers:

* against the real :data:`app.main.app` (via the ``client`` fixture) for the
  realistic /web 404, proving the whole middleware stack diverts correctly;
* against a tiny standalone app that wires only ``add_exception_handlers`` for
  the 500 / 403-AppError / 422 cases, so we can inject failures without
  registering throwaway routes on the shared app (which the route-test-matrix
  audit + OpenAPI snapshot would otherwise see).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.errors import AppError, add_exception_handlers

_HTML_ACCEPT = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_JSON_ACCEPT = {"Accept": "application/json"}


# ── Standalone harness: exception handlers + a request_id stamp, nothing else ──


def _make_handler_app() -> FastAPI:
    app = FastAPI()
    add_exception_handlers(app)

    @app.middleware("http")
    async def _stamp_request_id(request: Request, call_next):
        # Mirror SanitizedLoggingMiddleware: handlers echo request.state.request_id.
        request.state.request_id = "testrid0000abcd"
        return await call_next(request)

    @app.get("/web/boom")
    async def _web_boom() -> JSONResponse:  # pragma: no cover - body never returns
        raise RuntimeError("simulated /web 500 — secret path C:\\\\secret\\\\trace")

    @app.get("/api/boom")
    async def _api_boom() -> JSONResponse:  # pragma: no cover - body never returns
        raise RuntimeError("simulated /api 500")

    @app.get("/web/denied")
    async def _web_denied() -> JSONResponse:  # pragma: no cover - body never returns
        raise AppError("permission_denied", status_code=403)

    @app.get("/web/needs-int")
    async def _web_needs_int(n: int) -> JSONResponse:
        return JSONResponse({"n": n})

    return app


# ── Real-app integration: /web 404 ────────────────────────────────────────────


def test_web_404_with_html_accept_returns_html_page(client: TestClient) -> None:
    resp = client.get("/web/__no_such_page__", headers=_HTML_ACCEPT)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "这个页面不存在" in body
    # A way back, and the request_id for support — both required by the spec.
    assert 'href="/web"' in body
    assert resp.headers["X-Request-Id"] in body
    # §4 / §10: no leak of the JSON error code, host path, or stack.
    assert "route_not_found" not in body
    assert "C:\\" not in body and "E:\\" not in body
    assert "Traceback" not in body


def test_web_404_with_json_accept_keeps_json_envelope(client: TestClient) -> None:
    resp = client.get("/web/__no_such_page__", headers=_JSON_ACCEPT)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    # Byte-shape of the legacy envelope is unchanged.
    assert body["error"] == "route_not_found"
    assert body["message"]  # Chinese copy from ERROR_MESSAGES
    assert body["request_id"] == resp.headers["X-Request-Id"]


def test_web_404_without_accept_keeps_json_envelope(client: TestClient) -> None:
    # Only an explicit HTML preference diverts; a no-Accept caller (curl, a
    # script) still gets JSON.
    resp = client.get("/web/__no_such_page__")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["error"] == "route_not_found"


def test_api_404_with_html_accept_still_json(client: TestClient) -> None:
    # The hard guarantee: an /api path is NEVER turned into HTML even if a
    # client (an Android WebView, a misconfigured fetch) sends Accept: text/html.
    resp = client.get("/api/__no_such_endpoint__", headers=_HTML_ACCEPT)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["error"] == "route_not_found"


# ── Standalone harness: 500 / 403 AppError / 422 ──────────────────────────────


def test_web_500_with_html_accept_is_html_without_stack() -> None:
    app = _make_handler_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/web/boom", headers=_HTML_ACCEPT)
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "暂时出了点问题" in body
    assert "testrid0000abcd" in body  # request_id surfaced
    # No stack, no leaked exception text, no host path.
    assert "Traceback" not in body
    assert "RuntimeError" not in body
    assert "simulated" not in body
    assert "C:\\" not in body


def test_web_500_with_json_accept_keeps_server_error_envelope() -> None:
    app = _make_handler_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/web/boom", headers=_JSON_ACCEPT)
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["error"] == "server_error"
    assert "simulated" not in resp.text  # exception detail never reaches the body


def test_api_500_with_html_accept_still_json() -> None:
    app = _make_handler_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/boom", headers=_HTML_ACCEPT)
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["error"] == "server_error"


def test_web_app_error_403_with_html_accept_is_permission_page() -> None:
    app = _make_handler_app()
    with TestClient(app) as c:
        resp = c.get("/web/denied", headers=_HTML_ACCEPT)
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("text/html")
    assert "没有权限" in resp.text


def test_web_app_error_403_with_json_accept_keeps_envelope() -> None:
    app = _make_handler_app()
    with TestClient(app) as c:
        resp = c.get("/web/denied", headers=_JSON_ACCEPT)
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "permission_denied"
    assert body["request_id"] == "testrid0000abcd"


def test_web_validation_422_with_html_accept_is_html() -> None:
    app = _make_handler_app()
    with TestClient(app) as c:
        resp = c.get("/web/needs-int?n=not-a-number", headers=_HTML_ACCEPT)
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("text/html")
    # Generic 4xx copy (422 has no dedicated bucket); never the raw pydantic detail.
    assert "请求无法完成" in resp.text
    assert "not-a-number" not in resp.text


def test_web_validation_422_with_json_accept_keeps_envelope() -> None:
    app = _make_handler_app()
    with TestClient(app) as c:
        resp = c.get("/web/needs-int?n=not-a-number", headers=_JSON_ACCEPT)
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


def test_owner_404_with_html_accept_returns_html_page() -> None:
    # /owner is the second HTML-serving prefix. The standalone app has no /owner
    # route, so any /owner path 404s through http_error_handler.
    app = _make_handler_app()
    with TestClient(app) as c:
        resp = c.get("/owner/__nope__", headers=_HTML_ACCEPT)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "这个页面不存在" in resp.text
    # The way back stays on the operator surface, not the session-gated /web.
    assert 'href="/owner"' in resp.text
