"""Localhost HTTP control server for the Desktop Manager."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol, cast

from backend_manager.app_controller import ManagerShuttingDownError
from backend_manager.control_product_routes import (
    OWNER_SHORTCUTS,
    serve_owner_shortcut,
    serve_product_ledger_switch,
    serve_product_ledgers,
    serve_product_pair,
    serve_product_session,
    serve_product_unpair,
    serve_web_bootstrap,
    serve_web_bridge,
)
from backend_manager.control_security import (
    CHALLENGE_PATTERN,
    CONTENT_SECURITY_POLICY,
    CONTROL_SESSION_COOKIE,
    IDENTITY,
    REOPEN_REQUEST_CONTEXT,
    REOPEN_RESPONSE_CONTEXT,
    SHA256_PROOF_PATTERN,
    EmptyRequestBodyState,
    host_allowed,
    is_authorized,
    probe_existing_manager,
    read_empty_request_body_state,
    request_existing_manager_window,
    sign_challenge,
    token_allowed,
)
from backend_manager.web_bff import (
    ASSET_SESSION_COOKIE,
    SESSION_COOKIE,
    browser_session_valid,
)
from backend_manager.windows_user_security import set_exact_user_acl

__all__ = [
    "ControlServer",
    "Controller",
    "is_authorized",
    "probe_existing_manager",
    "request_existing_manager_window",
]

_TOKEN_PLACEHOLDER = "__CONTROL_TOKEN__"
_CONTROL_SESSION_COOKIE = CONTROL_SESSION_COOKIE
_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY
_OWNER_SHORTCUTS = OWNER_SHORTCUTS
_DEFAULT_UI_DIR = Path(__file__).resolve().parent
_UI_ASSETS = {
    "/assets/ui.css": ("ui.css", "text/css; charset=utf-8"),
    "/assets/ui.js": ("ui.js", "text/javascript; charset=utf-8"),
}
_UI_ASSET_FILENAMES = tuple(filename for filename, _ in _UI_ASSETS.values())


def _resolve_ui_asset_dir(ui_html: Path) -> Path:
    sibling_dir = ui_html.parent
    if all((sibling_dir / filename).is_file() for filename in _UI_ASSET_FILENAMES):
        return sibling_dir
    return _DEFAULT_UI_DIR
_ACTIONS = (
    "start",
    "stop",
    "restart",
    "auto_restart",
    "open_console",
    "open_pairing",
    "open_devices",
    "open_upload_links",
    "open_diagnostics",
    "open_settings",
    "export_diagnostics",
    "refresh_public_connectivity",
    "run_full_public_connectivity_check",
    "configure_connector",
    "reconnect_connector",
    "enable_connector",
    "pause_connector",
    "remove_connector",
    "continue_connector",
)
_ACTION_PATHS = {f"/api/{action}": action for action in _ACTIONS}
_BOOTSTRAP_TTL_SECONDS = 60.0
_BOOTSTRAP_REPLAY_TTL_SECONDS = 300.0
_BOOTSTRAP_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_MAX_WEB_SESSIONS = 8


class Controller(Protocol):
    """App-wiring interface driven by the control server."""

    def status(self) -> dict: ...
    def product_principal(self) -> dict: ...
    def product_ledgers(self) -> list[dict]: ...
    def product_bridge_context(self): ...
    def note_product_bridge_auth_failure(self, status_code: int, failed_token: str) -> bool: ...
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
    def open_diagnostics(self) -> None: ...
    def open_settings(self) -> None: ...
    def export_diagnostics(self) -> None: ...
    def refresh_public_connectivity(self) -> None: ...
    def run_full_public_connectivity_check(self) -> None: ...
    def configure_connector(self) -> None: ...
    def reconnect_connector(self) -> None: ...
    def enable_connector(self) -> None: ...
    def pause_connector(self) -> None: ...
    def remove_connector(self) -> None: ...
    def continue_connector(self) -> None: ...
    def is_manager_shutting_down(self) -> bool: ...


class _Handler(BaseHTTPRequestHandler):
    server_version = "TicketboxBackendManager/1.0"

    def log_message(self, *_args: object) -> None:
        pass

    def _control_server(self) -> ControlServer:
        return cast(ControlServer, self.server)

    def end_headers(self) -> None:
        if getattr(self, "_web_bridge_response", False):
            super().end_headers()
            return
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _host_allowed(self) -> bool:
        return host_allowed(self.headers.get("Host"), self._control_server().expected_host)

    def _authorized(self) -> bool:
        srv = self._control_server()
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
        return token_allowed(self.headers.get("X-Control-Token"), self._control_server().token)

    def _serve_ui_page(self) -> None:
        srv = self._control_server()
        if not srv.browser_session_valid(
            self.headers.get("Cookie"),
            cookie_name=CONTROL_SESSION_COOKIE,
        ):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        body = srv.ui_html.read_text(encoding="utf-8").replace(_TOKEN_PLACEHOLDER, srv.token)
        self._send(200, body.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_ui_asset(self, path: str) -> None:
        srv = self._control_server()
        if not srv.browser_session_valid(
            self.headers.get("Cookie"),
            cookie_name=CONTROL_SESSION_COOKIE,
        ):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        filename, content_type = _UI_ASSETS[path]
        payload = srv.read_ui_asset(filename)
        if payload is None:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, payload, content_type)

    def _serve_identity(self, raw_query: str) -> None:
        srv = self._control_server()
        try:
            query = urllib.parse.parse_qs(raw_query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            self._send(400, b"invalid challenge", "text/plain; charset=utf-8")
            return
        challenge_values = query.get("challenge")
        if set(query) != {"challenge"} or challenge_values is None or len(challenge_values) != 1:
            self._send(400, b"invalid challenge", "text/plain; charset=utf-8")
            return
        challenge = challenge_values[0]
        if not CHALLENGE_PATTERN.fullmatch(challenge):
            self._send(400, b"invalid challenge", "text/plain; charset=utf-8")
            return
        proof = sign_challenge(srv.instance_secret, challenge)
        self._send_json({**IDENTITY, "challenge": challenge, "proof": proof})

    def _serve_status(self) -> None:
        if not self._token_allowed():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        self._send_json(self._control_server().controller.status())

    def _serve_reopen(self) -> None:
        srv = self._control_server()
        challenge = self.headers.get("X-Ticketbox-Reopen-Challenge", "")
        request_proof = self.headers.get("X-Ticketbox-Reopen-Proof", "")
        body_state = read_empty_request_body_state(self)
        if body_state is EmptyRequestBodyState.INCOMPLETE:
            return
        if (
            body_state is EmptyRequestBodyState.DRAINED_NONEMPTY
            or self.headers.get("Origin") is not None
            or self.headers.get("Sec-Fetch-Site") is not None
            or not CHALLENGE_PATTERN.fullmatch(challenge)
            or not SHA256_PROOF_PATTERN.fullmatch(request_proof)
        ):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        expected_request_proof = sign_challenge(
            srv.instance_secret,
            challenge,
            context=REOPEN_REQUEST_CONTEXT,
        )
        if not secrets.compare_digest(request_proof, expected_request_proof):
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        if srv.controller.is_manager_shutting_down() or not srv.request_window():
            self._send_json({"error": "manager_shutting_down"}, code=409)
            return
        proof = sign_challenge(
            srv.instance_secret,
            challenge,
            context=REOPEN_RESPONSE_CONTEXT,
        )
        self._send_json({**IDENTITY, "challenge": challenge, "proof": proof})

    def _serve_control_action(self, action: str) -> None:
        srv = self._control_server()
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain; charset=utf-8")
            return
        body_state = read_empty_request_body_state(self)
        if body_state is EmptyRequestBodyState.INCOMPLETE:
            return
        if body_state is EmptyRequestBodyState.DRAINED_NONEMPTY:
            self._send(400, b"request body not allowed", "text/plain; charset=utf-8")
            return
        if srv.controller.is_manager_shutting_down():
            self._send_json({"error": "manager_shutting_down"}, code=409)
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

    def _serve_unrouted(self, parsed_path: urllib.parse.SplitResult) -> None:
        window_icon = self._control_server().window_icon
        if parsed_path.path == "/favicon.ico" and not parsed_path.query and window_icon is not None:
            self._send(200, window_icon, "image/x-icon")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        parsed_path = urllib.parse.urlsplit(self.path)
        path = parsed_path.path
        if path == "/web" or path.startswith(("/web/", "/static/web/", "/static/shared/")):
            serve_web_bridge(self)
        elif path == "/owner" or path.startswith("/owner/"):
            serve_owner_shortcut(self, path)
        elif path in ("/", "/index.html") and not parsed_path.query:
            self._serve_ui_page()
        elif path in _UI_ASSETS and not parsed_path.query:
            self._serve_ui_asset(path)
        elif path == "/api/identity":
            self._serve_identity(parsed_path.query)
        elif path == "/api/product/session":
            serve_product_session(self)
        elif path == "/api/product/ledgers":
            serve_product_ledgers(self)
        elif self.path == "/api/status":
            self._serve_status()
        else:
            self._serve_unrouted(parsed_path)

    def do_HEAD(self) -> None:
        if self.path == "/web" or self.path.startswith(("/web/", "/static/web/", "/static/shared/")):
            serve_web_bridge(self)
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_PUT(self) -> None:
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain; charset=utf-8")
            return
        parsed_path = urllib.parse.urlsplit(self.path)
        path = parsed_path.path
        if path == "/api/bootstrap" and not parsed_path.query:
            serve_web_bootstrap(self)
            return
        if path == "/web" or path.startswith("/web/"):
            serve_web_bridge(self)
            return
        if path == "/api/product/ledger/switch" and not parsed_path.query:
            serve_product_ledger_switch(self)
            return
        if path == "/api/product/pair" and not parsed_path.query:
            serve_product_pair(self)
            return
        if path == "/api/product/unpair" and not parsed_path.query:
            serve_product_unpair(self)
            return
        if self.path == "/api/reopen":
            self._serve_reopen()
            return
        action = _ACTION_PATHS.get(self.path)
        if action is None:
            self._send(404, b"unknown action", "text/plain; charset=utf-8")
            return
        self._serve_control_action(action)


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
        window_icon: Path | None = None,
        request_window: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__((host, port), _Handler)
        self.controller = controller
        self.token = token
        self.instance_secret = instance_secret
        self.ui_html = ui_html
        self._ui_asset_dir = _resolve_ui_asset_dir(ui_html)
        self.window_icon = window_icon.read_bytes() if window_icon is not None else None
        self.request_window = request_window or (lambda: False)
        self.action_lock = threading.Lock()
        self._web_session_lock = threading.Lock()
        self._web_session_digests = {
            cookie_name: deque(maxlen=_MAX_WEB_SESSIONS)
            for cookie_name in (
                SESSION_COOKIE,
                ASSET_SESSION_COOKIE,
                CONTROL_SESSION_COOKIE,
            )
        }
        self._bootstrap_lock = threading.Lock()
        self._bootstrap_pending: dict[str, tuple[float, Path]] = {}
        self._bootstrap_consumed: dict[str, float] = {}
        actual_port = int(self.server_address[1])
        self.expected_host = f"{host}:{actual_port}"
        self.expected_origin = f"http://{self.expected_host}"

    def read_ui_asset(self, filename: str) -> bytes | None:
        candidate = self._ui_asset_dir / filename
        return candidate.read_bytes() if candidate.is_file() else None

    def issue_web_session(self) -> dict[str, str]:
        session_ids = {cookie_name: secrets.token_urlsafe(48) for cookie_name in self._web_session_digests}
        with self._web_session_lock:
            for cookie_name, session_id in session_ids.items():
                digest = hashlib.sha256(session_id.encode("ascii")).hexdigest()
                self._web_session_digests[cookie_name].append(digest)
        return session_ids

    def browser_session_valid(self, cookie_header: str | None, *, cookie_name: str) -> bool:
        with self._web_session_lock:
            expected = tuple(self._web_session_digests[cookie_name])
        return browser_session_valid(
            cookie_header,
            expected,
            cookie_name=cookie_name,
        )

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
        path = Path(os.path.abspath(material_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            set_exact_user_acl(path.parent, directory=True)
        else:
            path.parent.chmod(0o700)
        token = secrets.token_urlsafe(32)
        action = f"{self.expected_origin}/api/bootstrap"
        document = (
            '<!doctype html><html lang="zh-CN" translate="no"><head><meta charset="utf-8">'
            '<meta name="google" content="notranslate">'
            "<title>正在打开小票夹</title></head><body>"
            f'<form method="post" action="{html.escape(action)}">'
            f'<input type="hidden" name="bootstrap_token" value="{html.escape(token)}">'
            "</form><script>document.forms[0].submit()</script></body></html>"
        )
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            self._remove_bootstrap_file(path)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
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
            self._bootstrap_pending[digest] = (now + _BOOTSTRAP_TTL_SECONDS, path)
        for expired_path in expired:
            self._remove_bootstrap_file(expired_path)
        return path.as_uri()

    def cancel_web_bootstrap(self, material_path: Path) -> None:
        path = Path(os.path.abspath(material_path))
        now = time.monotonic()
        cancelled_path: Path | None = None
        with self._bootstrap_lock:
            expired = self._expire_bootstraps(now)
            for digest, (_, pending_path) in tuple(self._bootstrap_pending.items()):
                if pending_path != path:
                    continue
                self._bootstrap_pending.pop(digest, None)
                self._bootstrap_consumed[digest] = now + _BOOTSTRAP_REPLAY_TTL_SECONDS
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
                    self._bootstrap_consumed[digest] = now + _BOOTSTRAP_REPLAY_TTL_SECONDS
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
