"""Web bootstrap, BFF relay, /owner shortcut, and product-session routes for the control server."""

from __future__ import annotations

import html
import http.client
import json
import urllib.parse
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from backend_manager.app_controller import ManagerShuttingDownError
from backend_manager.control_security import (
    CONTROL_SESSION_COOKIE,
    EmptyRequestBodyState,
    read_bounded_body,
    read_empty_request_body_state,
    read_json_body,
)
from backend_manager.product_data import ProductDataError
from backend_manager.web_bff import (
    ASSET_SESSION_COOKIE,
    MAX_REQUEST_BYTES,
    SESSION_COOKIE,
    BridgeResponse,
    WebBridgeError,
    relay,
    same_origin_request,
)

if TYPE_CHECKING:
    from backend_manager.control_server import _Handler

MAX_PRODUCT_BODY_BYTES = 1024
MAX_BOOTSTRAP_FORM_BYTES = 1024
OWNER_SHORTCUTS = {
    "/owner": "open_console",
    "/owner/pairing": "open_pairing",
    "/owner/devices": "open_devices",
    "/owner/upload-links": "open_upload_links",
    "/owner/diagnostics": "open_diagnostics",
    "/owner/settings": "open_settings",
}
_BRIDGE_FALLBACK_CSP = (
    "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; form-action 'self'"
)


def recovery_page(message: str, *, portable_available: bool = False) -> bytes:
    portable_link = (
        '<p><a href="/web/exports">下载有权访问的账本数据</a></p>'
        '<p><a href="/web/settings">设置与设备</a></p>'
        if portable_available
        else ""
    )
    return (
        '<!doctype html><meta charset=utf-8><meta name="google" content="notranslate">'
        "<title>小票夹需要恢复</title><h1>暂时无法打开账本</h1>"
        f"<p>{html.escape(message)}</p>"
        f"{portable_link}"
        '<p><a href="/">打开系统管理</a></p>'
    ).encode()


def _send_product_error(handler: _Handler, exc: ProductDataError) -> None:
    handler._send_json({"error": exc.error, "message": str(exc)}, code=exc.status_code)


def _run_locked_product_mutation(handler: _Handler, operation: Callable[[], dict]) -> None:
    srv = handler._control_server()
    if not srv.action_lock.acquire(blocking=False):
        handler._send_json({"error": "operation_in_progress"}, code=409)
        return
    try:
        try:
            response = operation()
        except ManagerShuttingDownError:
            handler._send_json({"error": "manager_shutting_down"}, code=409)
            return
        except ProductDataError as exc:
            _send_product_error(handler, exc)
            return
    finally:
        srv.action_lock.release()
    handler._send_json(response)


def _parse_bootstrap_token(handler: _Handler) -> str | None:
    if handler.headers.get("Transfer-Encoding") is not None:
        return None
    lengths = handler.headers.get_all("Content-Length", [])
    content_type = (handler.headers.get("Content-Type") or "").partition(";")[0].strip().lower()
    if len(lengths) != 1 or content_type != "application/x-www-form-urlencoded":
        return None
    try:
        length = int(lengths[0])
    except ValueError:
        return None
    if length <= 0 or length > MAX_BOOTSTRAP_FORM_BYTES:
        return None
    try:
        form = urllib.parse.parse_qs(
            handler.rfile.read(length).decode("ascii"),
            keep_blank_values=True,
            strict_parsing=True,
        )
    except (UnicodeDecodeError, ValueError):
        return None
    values = form.get("bootstrap_token")
    if set(form) != {"bootstrap_token"} or values is None or len(values) != 1:
        return None
    return values[0]


def serve_web_bootstrap(handler: _Handler) -> None:
    srv = handler._control_server()
    bootstrap_token = _parse_bootstrap_token(handler)
    if bootstrap_token is None:
        handler._send(400, b"invalid bootstrap", "text/plain; charset=utf-8")
        return
    status = srv.consume_web_bootstrap(bootstrap_token)
    if status != 200:
        handler._send(status, b"bootstrap rejected", "text/plain; charset=utf-8")
        return
    session_ids = srv.issue_web_session()
    body = (
        b'<!doctype html><meta charset=utf-8><meta name="google" content="notranslate">'
        b"<title>Opening Ticketbox</title>"
        b"<script>location.replace('/web')</script>"
    )
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header(
        "Set-Cookie",
        f"{SESSION_COOKIE}={session_ids[SESSION_COOKIE]}; Path=/web; HttpOnly; SameSite=Strict",
    )
    handler.send_header(
        "Set-Cookie",
        f"{ASSET_SESSION_COOKIE}={session_ids[ASSET_SESSION_COOKIE]}; Path=/static; HttpOnly; SameSite=Strict",
    )
    handler.send_header(
        "Set-Cookie",
        f"{CONTROL_SESSION_COOKIE}={session_ids[CONTROL_SESSION_COOKIE]}; Path=/; HttpOnly; SameSite=Strict",
    )
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _web_bridge_allowed(handler: _Handler) -> bool:
    srv = handler._control_server()
    path = urllib.parse.urlsplit(handler.path).path
    cookie_name = ASSET_SESSION_COOKIE if path.startswith("/static/") else SESSION_COOKIE
    return (
        handler._host_allowed()
        and srv.browser_session_valid(
            handler.headers.get("Cookie"),
            cookie_name=cookie_name,
        )
        and same_origin_request(
            method=handler.command,
            origin=handler.headers.get("Origin"),
            referer=handler.headers.get("Referer"),
            sec_fetch_site=handler.headers.get("Sec-Fetch-Site"),
            manager_origin=srv.expected_origin,
        )
    )


def _serve_web_unavailable(handler: _Handler, error: ProductDataError) -> None:
    if (
        error.error == "product_principal_required"
        and handler.command == "GET"
        and urllib.parse.urlsplit(handler.path).path in {"/web", "/web/"}
    ):
        handler.send_response(302)
        handler.send_header("Location", "/")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    message = (
        "桌面账本尚未绑定，请从系统管理完成绑定。"
        if error.status_code == 401
        else "小票夹服务尚未就绪，请先从系统管理恢复服务。"
    )
    handler._send(error.status_code, recovery_page(message), "text/html; charset=utf-8")


def _deliver_web_bridge(handler: _Handler, response: BridgeResponse) -> None:
    handler._web_bridge_response = True
    handler.send_response(response.status, response.reason)
    saw_length = False
    saw_csp = False
    for name, value in response.headers:
        lower = name.casefold()
        saw_length = saw_length or lower == "content-length"
        saw_csp = saw_csp or lower == "content-security-policy"
        handler.send_header(name, value)
    if not saw_length and response.download is None:
        handler.send_header("Content-Length", str(len(response.body)))
    if not saw_csp:
        handler.send_header("Content-Security-Policy", _BRIDGE_FALLBACK_CSP)
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    if handler.command != "HEAD":
        if response.download is None:
            handler.wfile.write(response.body)
        else:
            for chunk in response.download.chunks():
                handler.wfile.write(chunk)


def _is_ledger_forbidden_refusal(handler: _Handler, response: BridgeResponse) -> bool:
    if response.status != 403 or handler.command != "GET":
        return False
    with suppress(ValueError, UnicodeError):
        refusal = json.loads(response.body)
        return isinstance(refusal, dict) and refusal.get("error") == "ledger_forbidden"
    return False


def serve_web_bridge(handler: _Handler) -> None:
    srv = handler._control_server()
    if not _web_bridge_allowed(handler):
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    body = read_bounded_body(handler, max_bytes=MAX_REQUEST_BYTES)
    if body is None:
        handler._send(413, b"request rejected", "text/plain; charset=utf-8")
        return
    try:
        context = srv.controller.product_bridge_context()
        response = relay(
            context,
            method=handler.command,
            raw_target=handler.path,
            client_headers=handler.headers,
            body=body,
            manager_origin=srv.expected_origin,
            client_socket=handler.connection,
        )
    except ProductDataError as exc:
        _serve_web_unavailable(handler, exc)
        return
    except WebBridgeError as exc:
        if exc.status != 499:
            handler._send(exc.status, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
        return
    try:
        if srv.controller.note_product_bridge_auth_failure(response.status, context.app_token):
            path = urllib.parse.urlsplit(handler.path).path
            if not path.startswith("/api/"):
                handler._send(
                    401,
                    recovery_page("桌面身份已失效，请从系统管理重新绑定。"),
                    "text/html; charset=utf-8",
                )
                return
        if _is_ledger_forbidden_refusal(handler, response):
            handler._send(
                403,
                recovery_page(
                    "当前账本已归档或不再允许访问。你仍可核对账户有权下载的账本。",
                    portable_available=True,
                ),
                "text/html; charset=utf-8",
            )
            return
        try:
            _deliver_web_bridge(handler, response)
        except (OSError, http.client.HTTPException):
            handler.close_connection = True
    finally:
        response.close()


def serve_owner_shortcut(handler: _Handler, path: str) -> None:
    srv = handler._control_server()
    if not srv.browser_session_valid(
        handler.headers.get("Cookie"),
        cookie_name=CONTROL_SESSION_COOKIE,
    ):
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    action = OWNER_SHORTCUTS.get(path)
    if action is None:
        handler._send(404, b"not found", "text/plain; charset=utf-8")
        return
    getattr(srv.controller, action)()
    handler._send(
        200,
        (
            '<!doctype html><meta charset=utf-8><meta name="google" content="notranslate"><title>已打开系统管理</title>'
            "<h1>已在本机默认浏览器打开系统管理页面</h1>"
            '<p><a href="/web">返回日常账务</a> · <a href="/">返回管理器</a></p>'
        ).encode(),
        "text/html; charset=utf-8",
    )


def serve_product_session(handler: _Handler) -> None:
    srv = handler._control_server()
    if not handler._token_allowed():
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    try:
        payload = srv.controller.product_principal()
    except ProductDataError as exc:
        _send_product_error(handler, exc)
        return
    handler._send_json(payload)


def serve_product_ledgers(handler: _Handler) -> None:
    srv = handler._control_server()
    if not handler._token_allowed():
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    try:
        payload = srv.controller.product_ledgers()
    except ProductDataError as exc:
        _send_product_error(handler, exc)
        return
    handler._send_json({"ledgers": payload})


def serve_product_pair(handler: _Handler) -> None:
    srv = handler._control_server()
    if not handler._authorized():
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    payload = read_json_body(handler, max_bytes=MAX_PRODUCT_BODY_BYTES)
    if payload is None or set(payload) != {"pairing_code"} or not isinstance(payload["pairing_code"], str):
        handler._send_json({"error": "invalid_request"}, code=400)
        return
    pairing_code = payload["pairing_code"]
    _run_locked_product_mutation(handler, lambda: srv.controller.pair_product_principal(pairing_code))


def serve_product_unpair(handler: _Handler) -> None:
    srv = handler._control_server()
    if not handler._authorized():
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    body_state = read_empty_request_body_state(handler)
    if body_state is EmptyRequestBodyState.INCOMPLETE:
        return
    if body_state is EmptyRequestBodyState.DRAINED_NONEMPTY:
        handler._send_json({"error": "invalid_request"}, code=400)
        return
    _run_locked_product_mutation(handler, srv.controller.unpair_product_principal)


def serve_product_ledger_switch(handler: _Handler) -> None:
    srv = handler._control_server()
    if not handler._authorized():
        handler._send(403, b"forbidden", "text/plain; charset=utf-8")
        return
    payload = read_json_body(handler, max_bytes=MAX_PRODUCT_BODY_BYTES)
    if payload is None or set(payload) != {"ledger_id"} or not isinstance(payload["ledger_id"], str):
        handler._send_json({"error": "invalid_request"}, code=400)
        return
    ledger_id = payload["ledger_id"]
    _run_locked_product_mutation(handler, lambda: srv.controller.switch_product_principal_ledger(ledger_id))
