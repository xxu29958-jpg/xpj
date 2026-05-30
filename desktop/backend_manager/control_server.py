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

GET endpoints are read-only and localhost-bound, so they stay open.
"""

from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

_TOKEN_PLACEHOLDER = "__CONTROL_TOKEN__"
_ACTIONS = ("start", "stop", "restart", "auto_restart", "open_console")


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
) -> bool:
    """Whether a mutating request may proceed (token + same-origin)."""
    if not provided_token or not secrets.compare_digest(provided_token.encode(), token.encode()):
        return False
    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        return False
    return origin is None or origin == expected_origin


class _Handler(BaseHTTPRequestHandler):
    server_version = "TicketboxBackendManager/1.0"

    def log_message(self, *_args: object) -> None:  # silence stderr access logging
        pass

    # ---- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _expected_origin(self) -> str:
        return f"http://{self.headers.get('Host', '')}"

    def _authorized(self) -> bool:
        srv: ControlServer = self.server  # type: ignore[assignment]
        return is_authorized(
            token=srv.token,
            provided_token=self.headers.get("X-Control-Token"),
            sec_fetch_site=self.headers.get("Sec-Fetch-Site"),
            origin=self.headers.get("Origin"),
            expected_origin=self._expected_origin(),
        )

    # ---- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
        if self.path in ("/", "/index.html"):
            html = srv.ui_html.read_text(encoding="utf-8").replace(_TOKEN_PLACEHOLDER, srv.token)
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send_json(srv.controller.status())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        srv: ControlServer = self.server  # type: ignore[assignment]
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

    def __init__(self, host: str, port: int, *, controller: Controller, token: str, ui_html: Path) -> None:
        super().__init__((host, port), _Handler)
        self.controller = controller
        self.token = token
        self.ui_html = ui_html
