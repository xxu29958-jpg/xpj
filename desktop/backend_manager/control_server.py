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
import ipaddress
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

_TOKEN_PLACEHOLDER = "__CONTROL_TOKEN__"
_ACTIONS = ("start", "stop", "restart", "auto_restart", "open_console")
_IDENTITY = {"product": "ticketbox-desktop-manager", "protocol": "v1"}
_IDENTITY_RESPONSE_LIMIT = 512
_CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


def manager_window_url(manager_url: str, instance_secret: str) -> str:
    return f"{manager_url}?{urllib.parse.urlencode({'instance': instance_secret})}"


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


class Controller(Protocol):
    """What the control server drives — implemented by the app wiring."""

    def status(self) -> dict: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def restart(self) -> None: ...
    def auto_restart(self) -> None: ...
    def open_console(self) -> None: ...


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
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
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

    # ---- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        parsed_path = urllib.parse.urlsplit(self.path)
        if parsed_path.path in ("/", "/index.html"):
            try:
                query = urllib.parse.parse_qs(parsed_path.query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                query = {}
            provided = query.get("instance")
            if (
                set(query) != {"instance"}
                or provided is None
                or len(provided) != 1
                or not secrets.compare_digest(provided[0], srv.instance_secret)
            ):
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            html = srv.ui_html.read_text(encoding="utf-8").replace(_TOKEN_PLACEHOLDER, srv.token)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
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
        elif self.path == "/api/status":
            if not self._token_allowed():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            self._send_json(srv.controller.status())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        action = self.path.rsplit("/", 1)[-1]
        if action not in _ACTIONS:
            self._send(404, b"unknown action", "text/plain; charset=utf-8")
            return
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        getattr(srv.controller, action)()
        self._send_json(srv.controller.status())


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
    ) -> None:
        super().__init__((host, port), _Handler)
        self.controller = controller
        self.token = token
        self.instance_secret = instance_secret
        self.ui_html = ui_html
        actual_port = int(self.server_address[1])
        self.expected_host = f"{host}:{actual_port}"
        self.expected_origin = f"http://{self.expected_host}"
