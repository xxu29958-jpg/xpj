"""Localhost HTTP control surface for the GUI — CSRF-safe.

The mutating endpoints (start / stop / restart …) run real process control, so an
unauthenticated localhost server would be a CSRF hole: any web page the user has
open could ``fetch('http://127.0.0.1:<port>/api/stop')`` and DoS the backend. Three
layers stop that, all enforced by [is_authorized] on every POST:

1. a per-process bearer token (in the served HTML, unreadable cross-origin) — and
   requiring a custom header forces a CORS preflight that this server never grants,
   so a cross-site POST is rejected before it is even sent;
2. a ``Sec-Fetch-Site`` check (reject anything but same-origin / direct navigation);
3. an ``Origin`` check (reject a foreign origin).

GET endpoints are read-only, localhost-bound, and reject any Host other than the
canonical address selected at startup. That last check prevents DNS rebinding
from turning an attacker-controlled origin into the local control origin.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

from backend_manager.app_controller import ManagerShuttingDownError
from backend_manager.product_data import ProductDataError
from backend_manager.web_bff import (
    ASSET_SESSION_COOKIE,
    MAX_REQUEST_BYTES,
    PREFERENCE_SESSION_COOKIE,
    SESSION_COOKIE,
    WebBridgeError,
    browser_session_valid,
    relay,
    same_origin_request,
)
from backend_manager.windows_user_security import set_exact_user_acl

_TOKEN_PLACEHOLDER = "__CONTROL_TOKEN__"
_CONTROL_SESSION_COOKIE = "ticketbox_manager_control"
_ACTIONS = (
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
)
_ACTION_PATHS = {f"/api/{action}": action for action in _ACTIONS}
_IDENTITY = {"product": "ticketbox-desktop-manager", "protocol": "v1"}
_IDENTITY_RESPONSE_LIMIT = 512
_CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_SHA256_PROOF_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PRODUCT_BODY_BYTES = 1024
_MAX_BOOTSTRAP_FORM_BYTES = 1024
_BOOTSTRAP_TTL_SECONDS = 60.0
_BOOTSTRAP_REPLAY_TTL_SECONDS = 300.0
_BOOTSTRAP_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_REOPEN_REQUEST_CONTEXT = b"ticketbox-manager-reopen-request-v1\0"
_REOPEN_RESPONSE_CONTEXT = b"ticketbox-manager-reopen-response-v1\0"
_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


def _normalized_host(host: str) -> str | None:
    value = host.strip().strip("[]").casefold()
    if not value:
        return None
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        if value == "localhost":
            return value
        return None


def _authority_tuple(value: str, *, scheme: str) -> tuple[str, str, int] | None:
    try:
        parsed = urllib.parse.urlsplit(f"{scheme}://{value.strip()}")
        port = parsed.port
    except ValueError:
        return None
    host = _normalized_host(parsed.hostname or "")
    if (
        parsed.scheme.casefold() != scheme
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return scheme, host, port if port is not None else 80


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    host = _normalized_host(parsed.hostname or "")
    if (
        scheme != "http"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return scheme, host, port if port is not None else 80


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def probe_existing_manager(manager_url: str, instance_secret: str, *, timeout: float = 0.5) -> bool:
    """Recognize an already-running local Manager before reopening its window."""
    try:
        parsed = urllib.parse.urlsplit(manager_url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        return False
    try:
        loopback_v4 = (
            ipaddress.ip_address(hostname).version == 4
            and ipaddress.ip_address(hostname).is_loopback
        )
    except ValueError:
        loopback_v4 = False
    if (
        parsed.scheme != "http"
        or not (hostname == "localhost" or loopback_v4)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/"
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        return False
    challenge = secrets.token_urlsafe(32)
    identity_url = urllib.parse.urljoin(manager_url, "api/identity")
    identity_url = f"{identity_url}?{urllib.parse.urlencode({'challenge': challenge})}"
    request = urllib.request.Request(identity_url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - validated loopback
            if response.status != 200:
                return False
            media_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
            if media_type != "application/json":
                return False
            raw = response.read(_IDENTITY_RESPONSE_LIMIT + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    if len(raw) > _IDENTITY_RESPONSE_LIMIT:
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or set(payload) != {*_IDENTITY, "challenge", "proof"}:
        return False
    expected_proof = hmac.new(
        instance_secret.encode("utf-8"),
        challenge.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    proof = payload.get("proof")
    return (
        payload.get("product") == _IDENTITY["product"]
        and payload.get("protocol") == _IDENTITY["protocol"]
        and payload.get("challenge") == challenge
        and isinstance(proof, str)
        and secrets.compare_digest(proof, expected_proof)
    )


def request_existing_manager_window(
    manager_url: str,
    instance_secret: str,
    *,
    timeout: float = 0.5,
) -> bool:
    """Ask the authenticated owner process to open and own another UI window."""
    if not probe_existing_manager(manager_url, instance_secret, timeout=timeout):
        return False
    challenge = secrets.token_urlsafe(32)
    request_proof = hmac.new(
        instance_secret.encode("utf-8"),
        _REOPEN_REQUEST_CONTEXT + challenge.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    reopen_url = urllib.parse.urljoin(manager_url, "api/reopen")
    request = urllib.request.Request(
        reopen_url,
        data=b"",
        headers={
            "Accept": "application/json",
            "X-Ticketbox-Reopen-Challenge": challenge,
            "X-Ticketbox-Reopen-Proof": request_proof,
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - validated loopback
            if response.status != 200:
                return False
            media_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
            if media_type != "application/json":
                return False
            raw = response.read(_IDENTITY_RESPONSE_LIMIT + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return False
    if len(raw) > _IDENTITY_RESPONSE_LIMIT:
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or set(payload) != {*_IDENTITY, "challenge", "proof"}:
        return False
    expected_proof = hmac.new(
        instance_secret.encode("utf-8"),
        _REOPEN_RESPONSE_CONTEXT + challenge.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    proof = payload.get("proof")
    return (
        payload.get("product") == _IDENTITY["product"]
        and payload.get("protocol") == _IDENTITY["protocol"]
        and payload.get("challenge") == challenge
        and isinstance(proof, str)
        and secrets.compare_digest(proof, expected_proof)
    )


class Controller(Protocol):
    """What the control server drives — implemented by the app wiring."""

    def status(self) -> dict: ...
    def product_principal(self) -> dict: ...
    def product_ledgers(self) -> list[dict]: ...
    def product_bridge_context(self): ...
    def pair_product_principal(self, pairing_code: str) -> dict: ...
    def switch_product_principal_ledger(self, ledger_id: str) -> dict: ...
    def unpair_product_principal(self) -> dict: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def restart(self) -> None: ...
    def auto_restart(self) -> None: ...
    def open_console(self) -> None: ...
    def open_pairing(self) -> None: ...
    def open_devices(self) -> None: ...
    def open_upload_links(self) -> None: ...
    def open_backups(self) -> None: ...
    def open_diagnostics(self) -> None: ...
    def open_settings(self) -> None: ...
    def export_diagnostics(self) -> None: ...
    def is_manager_shutting_down(self) -> bool: ...


def is_authorized(
    *,
    token: str,
    provided_token: str | None,
    sec_fetch_site: str | None,
    origin: str | None,
    expected_origin: str,
    provided_host: str | None,
    expected_host: str,
) -> bool:
    """Whether a mutating request may proceed (token + same-origin)."""
    expected_authority = _authority_tuple(expected_host, scheme="http")
    if (
        expected_authority is None
        or provided_host is None
        or _authority_tuple(provided_host, scheme="http") != expected_authority
    ):
        return False
    if not provided_token or not secrets.compare_digest(provided_token.encode(), token.encode()):
        return False
    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        return False
    expected_origin_tuple = _origin_tuple(expected_origin)
    return origin is None or (
        expected_origin_tuple is not None
        and _origin_tuple(origin) == expected_origin_tuple
    )


class _Handler(BaseHTTPRequestHandler):
    server_version = "TicketboxBackendManager/1.0"

    def log_message(self, *_args: object) -> None:  # silence stderr access logging
        pass

    def end_headers(self) -> None:
        if getattr(self, "_web_bridge_response", False):
            # Bridge responses carry the backend's own headers (plus the
            # fallback CSP _serve_web_bridge adds); never overwrite them.
            super().end_headers()
            return
        self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    # ---- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_json_list(self, payload: list, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _serve_web_bootstrap(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if self.headers.get("Transfer-Encoding") is not None:
            self._send(400, b"invalid bootstrap", "text/plain; charset=utf-8")
            return
        lengths = self.headers.get_all("Content-Length", [])
        content_type = (self.headers.get("Content-Type") or "").partition(";")[0].strip().lower()
        if len(lengths) != 1 or content_type != "application/x-www-form-urlencoded":
            self._send(400, b"invalid bootstrap", "text/plain; charset=utf-8")
            return
        try:
            length = int(lengths[0])
        except ValueError:
            length = -1
        if length <= 0 or length > _MAX_BOOTSTRAP_FORM_BYTES:
            self._send(400, b"invalid bootstrap", "text/plain; charset=utf-8")
            return
        try:
            form = urllib.parse.parse_qs(
                self.rfile.read(length).decode("ascii"),
                keep_blank_values=True,
                strict_parsing=True,
            )
        except (UnicodeDecodeError, ValueError):
            form = {}
        values = form.get("bootstrap_token")
        if set(form) != {"bootstrap_token"} or values is None or len(values) != 1:
            self._send(400, b"invalid bootstrap", "text/plain; charset=utf-8")
            return
        status = srv.consume_web_bootstrap(values[0])
        if status != 200:
            self._send(status, b"bootstrap rejected", "text/plain; charset=utf-8")
            return
        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>Opening Ticketbox</title>"
            b"<script>location.replace('/web')</script>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={srv.web_session_secret}; Path=/web; HttpOnly; SameSite=Strict",
        )
        self.send_header(
            "Set-Cookie",
            f"{ASSET_SESSION_COOKIE}={srv.web_session_secret}; Path=/static; HttpOnly; SameSite=Strict",
        )
        self.send_header(
            "Set-Cookie",
            f"{PREFERENCE_SESSION_COOKIE}={srv.web_session_secret}; "
            "Path=/api/me/ui-preferences; HttpOnly; SameSite=Strict",
        )
        self.send_header(
            "Set-Cookie",
            f"{_CONTROL_SESSION_COOKIE}={srv.web_session_secret}; "
            "Path=/; HttpOnly; SameSite=Strict",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _web_bridge_allowed(self) -> bool:
        srv: ControlServer = self.server  # type: ignore[assignment]
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/me/ui-preferences":
            cookie_name = PREFERENCE_SESSION_COOKIE
        elif path.startswith("/static/"):
            cookie_name = ASSET_SESSION_COOKIE
        else:
            cookie_name = SESSION_COOKIE
        return (
            self._host_allowed()
            and browser_session_valid(
                self.headers.get("Cookie"),
                srv.web_session_secret,
                cookie_name=cookie_name,
            )
            and same_origin_request(
                method=self.command,
                origin=self.headers.get("Origin"),
                referer=self.headers.get("Referer"),
                sec_fetch_site=self.headers.get("Sec-Fetch-Site"),
                manager_origin=srv.expected_origin,
            )
        )

    def _read_bridge_body(self) -> bytes | None:
        if self.headers.get("Transfer-Encoding") is not None:
            return None
        values = self.headers.get_all("Content-Length", [])
        if not values:
            return b""
        if len(values) != 1:
            return None
        try:
            length = int(values[0])
        except ValueError:
            return None
        if length < 0 or length > MAX_REQUEST_BYTES:
            return None
        return self.rfile.read(length)

    def _serve_web_bridge(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._web_bridge_allowed():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        body = self._read_bridge_body()
        if body is None:
            self._send(413, b"request rejected", "text/plain; charset=utf-8")
            return
        try:
            response = relay(
                srv.controller.product_bridge_context(),
                method=self.command,
                raw_target=self.path,
                client_headers=self.headers,
                body=body,
                manager_origin=srv.expected_origin,
            )
        except ProductDataError as exc:
            message = (
                "桌面账本尚未绑定，请从系统管理完成绑定。"
                if exc.status_code == 401
                else "小票夹服务尚未就绪，请先从系统管理恢复服务。"
            )
            self._send(
                exc.status_code,
                (
                    "<!doctype html><meta charset=utf-8>"
                    "<title>小票夹需要恢复</title><h1>暂时无法打开账本</h1>"
                    f"<p>{html.escape(message)}</p>"
                ).encode(),
                "text/html; charset=utf-8",
            )
            return
        except WebBridgeError as exc:
            self._send(exc.status, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._web_bridge_response = True
        self.send_response(response.status, response.reason)
        saw_length = False
        saw_csp = False
        for name, value in response.headers:
            lower = name.casefold()
            saw_length = saw_length or lower == "content-length"
            saw_csp = saw_csp or lower == "content-security-policy"
            self.send_header(name, value)
        if not saw_length:
            self.send_header("Content-Length", str(len(response.body)))
        if not saw_csp:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; form-action 'self'",
            )
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def _host_allowed(self) -> bool:
        srv: ControlServer = self.server  # type: ignore[assignment]
        provided = self.headers.get("Host")
        return provided is not None and _authority_tuple(
            provided,
            scheme="http",
        ) == _authority_tuple(srv.expected_host, scheme="http")

    def _authorized(self) -> bool:
        srv: ControlServer = self.server  # type: ignore[assignment]
        return is_authorized(
            token=srv.token,
            provided_token=self.headers.get("X-Control-Token"),
            sec_fetch_site=self.headers.get("Sec-Fetch-Site"),
            origin=self.headers.get("Origin"),
            expected_origin=srv.expected_origin,
            provided_host=self.headers.get("Host"),
            expected_host=srv.expected_host,
        )

    def _token_allowed(self) -> bool:
        srv: ControlServer = self.server  # type: ignore[assignment]
        provided = self.headers.get("X-Control-Token")
        return provided is not None and secrets.compare_digest(provided, srv.token)

    def _has_empty_request_body(self) -> bool:
        if self.headers.get("Transfer-Encoding") is not None:
            return False
        lengths = self.headers.get_all("Content-Length", [])
        return not lengths or (len(lengths) == 1 and lengths[0].strip() == "0")

    def _read_json_body(self, *, max_bytes: int) -> dict | None:
        if self.headers.get("Transfer-Encoding") is not None:
            return None
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            return None
        try:
            length = int(lengths[0])
        except ValueError:
            return None
        content_type = (self.headers.get("Content-Type") or "").partition(";")[0].strip().lower()
        if length <= 0 or length > max_bytes or content_type != "application/json":
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _send_product_error(self, exc: ProductDataError) -> None:
        self._send_json(
            {"error": exc.error, "message": str(exc)},
            code=exc.status_code,
        )

    def _serve_product_session(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._token_allowed():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        try:
            payload = srv.controller.product_principal()
        except ProductDataError as exc:
            self._send_product_error(exc)
            return
        self._send_json(payload)

    def _serve_product_ledgers(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._token_allowed():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        try:
            payload = srv.controller.product_ledgers()
        except ProductDataError as exc:
            self._send_product_error(exc)
            return
        self._send_json({"ledgers": payload})

    def _serve_product_pair(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        payload = self._read_json_body(max_bytes=_MAX_PRODUCT_BODY_BYTES)
        if payload is None or set(payload) != {"pairing_code"}:
            self._send_json({"error": "invalid_request"}, code=400)
            return
        pairing_code = payload["pairing_code"]
        if not isinstance(pairing_code, str):
            self._send_json({"error": "invalid_request"}, code=400)
            return
        if not srv.action_lock.acquire(blocking=False):
            self._send_json({"error": "operation_in_progress"}, code=409)
            return
        try:
            try:
                response = srv.controller.pair_product_principal(pairing_code)
            except ProductDataError as exc:
                self._send_product_error(exc)
                return
        finally:
            srv.action_lock.release()
        self._send_json(response)

    def _serve_product_unpair(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if not self._has_empty_request_body():
            self._send_json({"error": "invalid_request"}, code=400)
            return
        if not srv.action_lock.acquire(blocking=False):
            self._send_json({"error": "operation_in_progress"}, code=409)
            return
        try:
            try:
                response = srv.controller.unpair_product_principal()
            except ProductDataError as exc:
                self._send_product_error(exc)
                return
        finally:
            srv.action_lock.release()
        self._send_json(response)

    def _serve_product_ledger_switch(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        payload = self._read_json_body(max_bytes=_MAX_PRODUCT_BODY_BYTES)
        if payload is None or set(payload) != {"ledger_id"}:
            self._send_json({"error": "invalid_request"}, code=400)
            return
        ledger_id = payload["ledger_id"]
        if not isinstance(ledger_id, str):
            self._send_json({"error": "invalid_request"}, code=400)
            return
        if not srv.action_lock.acquire(blocking=False):
            self._send_json({"error": "operation_in_progress"}, code=409)
            return
        try:
            try:
                response = srv.controller.switch_product_principal_ledger(ledger_id)
            except ProductDataError as exc:
                self._send_product_error(exc)
                return
        finally:
            srv.action_lock.release()
        self._send_json(response)

    # ---- routes -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: C901 - explicit fail-closed route matrix
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        parsed_path = urllib.parse.urlsplit(self.path)
        if parsed_path.path == "/web" or parsed_path.path.startswith(("/web/", "/static/web/", "/static/shared/")):
            self._serve_web_bridge()
        elif parsed_path.path in ("/", "/index.html") and not parsed_path.query:
            if not browser_session_valid(
                self.headers.get("Cookie"),
                srv.web_session_secret,
                cookie_name=_CONTROL_SESSION_COOKIE,
            ):
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            body = srv.ui_html.read_text(encoding="utf-8").replace(
                _TOKEN_PLACEHOLDER,
                srv.token,
            )
            self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")
        elif parsed_path.path == "/api/identity":
            try:
                query = urllib.parse.parse_qs(parsed_path.query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                self._send(400, b"invalid challenge", "text/plain; charset=utf-8")
                return
            challenge_values = query.get("challenge")
            if set(query) != {"challenge"} or challenge_values is None or len(challenge_values) != 1:
                self._send(400, b"invalid challenge", "text/plain; charset=utf-8")
                return
            challenge = challenge_values[0]
            if not _CHALLENGE_PATTERN.fullmatch(challenge):
                self._send(400, b"invalid challenge", "text/plain; charset=utf-8")
                return
            proof = hmac.new(
                srv.instance_secret.encode("utf-8"),
                challenge.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            self._send_json({**_IDENTITY, "challenge": challenge, "proof": proof})
        elif parsed_path.path == "/api/product/session":
            self._serve_product_session()
        elif parsed_path.path == "/api/product/ledgers":
            self._serve_product_ledgers()
        elif self.path == "/api/status":
            if not self._token_allowed():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            self._send_json(srv.controller.status())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:
        if self.path == "/web" or self.path.startswith(("/web/", "/static/web/", "/static/shared/")):
            self._serve_web_bridge()
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_PUT(self) -> None:
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        parsed_path = urllib.parse.urlsplit(self.path)
        if parsed_path.path == "/api/me/ui-preferences" and not parsed_path.query:
            self._serve_web_bridge()
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: C901 - explicit fail-closed route matrix
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        parsed_path = urllib.parse.urlsplit(self.path)
        if parsed_path.path == "/api/bootstrap" and not parsed_path.query:
            self._serve_web_bootstrap()
            return
        if parsed_path.path == "/web" or parsed_path.path.startswith("/web/"):
            self._serve_web_bridge()
            return
        if parsed_path.path == "/api/product/ledger/switch" and not parsed_path.query:
            self._serve_product_ledger_switch()
            return
        if parsed_path.path == "/api/product/pair" and not parsed_path.query:
            self._serve_product_pair()
            return
        if parsed_path.path == "/api/product/unpair" and not parsed_path.query:
            self._serve_product_unpair()
            return
        if self.path == "/api/reopen":
            challenge = self.headers.get("X-Ticketbox-Reopen-Challenge", "")
            request_proof = self.headers.get("X-Ticketbox-Reopen-Proof", "")
            if (
                not self._has_empty_request_body()
                or self.headers.get("Origin") is not None
                or self.headers.get("Sec-Fetch-Site") is not None
                or not _CHALLENGE_PATTERN.fullmatch(challenge)
                or not _SHA256_PROOF_PATTERN.fullmatch(request_proof)
            ):
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            expected_request_proof = hmac.new(
                srv.instance_secret.encode("utf-8"),
                _REOPEN_REQUEST_CONTEXT + challenge.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            if not secrets.compare_digest(request_proof, expected_request_proof):
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            if srv.controller.is_manager_shutting_down() or not srv.request_window():
                self._send_json({"error": "manager_shutting_down"}, code=409)
                return
            proof = hmac.new(
                srv.instance_secret.encode("utf-8"),
                _REOPEN_RESPONSE_CONTEXT + challenge.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            self._send_json({**_IDENTITY, "challenge": challenge, "proof": proof})
            return
        action = _ACTION_PATHS.get(self.path)
        if action is None:
            self._send(404, b"unknown action", "text/plain; charset=utf-8")
            return
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if not self._has_empty_request_body():
            self._send(400, b"request body not allowed", "text/plain; charset=utf-8")
            return
        if not srv.action_lock.acquire(blocking=False):
            self._send_json({"error": "operation_in_progress"}, code=409)
            return
        try:
            try:
                getattr(srv.controller, action)()
                payload = srv.controller.status()
            except ManagerShuttingDownError:
                self._send_json({"error": "manager_shutting_down"}, code=409)
                return
        finally:
            srv.action_lock.release()
        self._send_json(payload)


class ControlServer(ThreadingHTTPServer):
    """Threading HTTP server bound to localhost, carrying the controller + auth token."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        controller: Controller,
        token: str,
        instance_secret: str,
        ui_html: Path,
        request_window: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__((host, port), _Handler)
        self.controller = controller
        self.token = token
        self.instance_secret = instance_secret
        self.ui_html = ui_html
        self.request_window = request_window or (lambda: False)
        self.web_session_secret = secrets.token_urlsafe(48)
        self.action_lock = threading.Lock()
        self._bootstrap_lock = threading.Lock()
        self._bootstrap_pending: dict[str, tuple[float, Path]] = {}
        self._bootstrap_consumed: dict[str, float] = {}
        actual_port = int(self.server_address[1])
        self.expected_host = f"{host}:{actual_port}"
        self.expected_origin = f"http://{self.expected_host}"

    @staticmethod
    def _bootstrap_digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _remove_bootstrap_file(path: Path) -> None:
        with suppress(OSError):
            path.unlink(missing_ok=True)

    def _expire_bootstraps(self, now: float) -> list[Path]:
        expired_paths: list[Path] = []
        for digest, (expires_at, path) in tuple(self._bootstrap_pending.items()):
            if expires_at <= now:
                self._bootstrap_pending.pop(digest, None)
                self._bootstrap_consumed[digest] = now + _BOOTSTRAP_REPLAY_TTL_SECONDS
                expired_paths.append(path)
        for digest, expires_at in tuple(self._bootstrap_consumed.items()):
            if expires_at <= now:
                self._bootstrap_consumed.pop(digest, None)
        return expired_paths

    def prepare_web_bootstrap(self, material_path: Path) -> str:
        """Create one ACL-restricted HTML POST bootstrap with a single-use token."""

        path = Path(os.path.abspath(material_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            set_exact_user_acl(path.parent, directory=True)
        else:
            path.parent.chmod(0o700)
        token = secrets.token_urlsafe(32)
        action = f"{self.expected_origin}/api/bootstrap"
        document = (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>正在打开小票夹</title></head><body>"
            f"<form method=\"post\" action=\"{html.escape(action)}\">"
            f"<input type=\"hidden\" name=\"bootstrap_token\" value=\"{html.escape(token)}\">"
            "</form><script>document.forms[0].submit()</script></body></html>"
        )
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(document)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == "nt":
                set_exact_user_acl(path, directory=False)
        except BaseException:
            self._remove_bootstrap_file(path)
            raise
        digest = self._bootstrap_digest(token)
        now = time.monotonic()
        with self._bootstrap_lock:
            expired = self._expire_bootstraps(now)
            self._bootstrap_pending[digest] = (
                now + _BOOTSTRAP_TTL_SECONDS,
                path,
            )
        for expired_path in expired:
            self._remove_bootstrap_file(expired_path)
        return path.as_uri()

    def cancel_web_bootstrap(self, material_path: Path) -> None:
        """Revoke one unconsumed launch grant and remove its restricted file."""

        path = Path(os.path.abspath(material_path))
        now = time.monotonic()
        cancelled_path: Path | None = None
        with self._bootstrap_lock:
            expired = self._expire_bootstraps(now)
            for digest, (_, pending_path) in tuple(self._bootstrap_pending.items()):
                if pending_path != path:
                    continue
                self._bootstrap_pending.pop(digest, None)
                self._bootstrap_consumed[digest] = (
                    now + _BOOTSTRAP_REPLAY_TTL_SECONDS
                )
                cancelled_path = pending_path
                break
        for expired_path in expired:
            self._remove_bootstrap_file(expired_path)
        if cancelled_path is not None:
            self._remove_bootstrap_file(cancelled_path)

    def consume_web_bootstrap(self, token: str) -> int:
        if not _BOOTSTRAP_TOKEN_PATTERN.fullmatch(token):
            return 401
        digest = self._bootstrap_digest(token)
        now = time.monotonic()
        with self._bootstrap_lock:
            expired = self._expire_bootstraps(now)
            if digest in self._bootstrap_consumed:
                status = 410
                path = None
            else:
                grant = self._bootstrap_pending.pop(digest, None)
                if grant is None:
                    status = 401
                    path = None
                else:
                    _, path = grant
                    self._bootstrap_consumed[digest] = (
                        now + _BOOTSTRAP_REPLAY_TTL_SECONDS
                    )
                    status = 200
        for expired_path in expired:
            self._remove_bootstrap_file(expired_path)
        if path is not None:
            self._remove_bootstrap_file(path)
        return status

    def server_close(self) -> None:
        with self._bootstrap_lock:
            paths = [path for _, path in self._bootstrap_pending.values()]
            self._bootstrap_pending.clear()
            self._bootstrap_consumed.clear()
        for path in paths:
            self._remove_bootstrap_file(path)
        super().server_close()
