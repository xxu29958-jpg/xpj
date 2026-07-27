"""Manager-to-backend Desktop bridge contracts (#219 two-phase)."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend_manager.product_data import (
    PendingProductSession,
    ProductDataError,
    activate_product_session,
    derive_desktop_pending_token,
    list_product_ledgers,
    new_activation_attempt,
    pair_product_session,
    revoke_product_session,
    switch_product_ledger,
)
from backend_manager.product_identity import ProductSession

# Known-answer vector computed by
# backend/app/services/session_lifecycle_service.py::
# derive_desktop_activation_token (the authoritative KDF).
_KAT_SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
_KAT_ATTEMPT_ID = "12345678-1234-5678-1234-567812345678"
_KAT_TOKEN = "tbx_-4F5emta7ZWJsn1RO0Ujfoy5hD1uW5EXWYsuQ0_IUVw"


class _Server:
    """One throwaway loopback HTTP server capturing JSON POSTs."""

    def __init__(self, handler) -> None:
        self.requests: list[dict] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever)

    def __enter__(self) -> _Server:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"


def _json_response(handler, payload: dict, *, status: int = 200) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def test_derive_desktop_pending_token_matches_backend_kdf() -> None:
    assert derive_desktop_pending_token(_KAT_SECRET, _KAT_ATTEMPT_ID) == _KAT_TOKEN


def test_new_activation_attempt_shape_and_uniqueness() -> None:
    first_id, first_secret = new_activation_attempt()
    second_id, second_secret = new_activation_attempt()

    assert str(uuid.UUID(first_id)) == first_id
    assert len(first_secret) == 43
    assert (first_id, first_secret) != (second_id, second_secret)
    # The generator feeds the derivation directly.
    assert derive_desktop_pending_token(first_secret, first_id).startswith("tbx_")


def test_pair_stages_client_derived_pending_and_activate_promotes_it() -> None:
    pair_body: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw) if raw else None
            server_requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "bridge": self.headers.get("X-Ticketbox-Desktop-Bridge"),
                    "previous": self.headers.get("X-Ticketbox-Previous-Session"),
                    "body": body,
                }
            )
            if self.path == "/api/auth/pair":
                pair_body.update(body)
                derived = derive_desktop_pending_token(
                    body["pairing_attempt_secret"],
                    body["pairing_attempt_id"],
                )
                _json_response(
                    self,
                    {
                        "session_token": derived,
                        "pairing_attempt_id": body["pairing_attempt_id"],
                        "server_id": "server-1",
                        "data_generation": "gen-1",
                        "account_public_id": "acct-1",
                        "device_public_id": "dev-1",
                        "account_name": "我",
                        "ledger_id": "owner",
                        "ledger_name": "我的小票夹",
                        "device_name": "小票夹 Desktop",
                        "role": "owner",
                        "expires_at": None,
                        "soft_refresh_after": None,
                        "activation_required": True,
                        "activation_expires_at": "2026-07-26T22:20:00Z",
                    },
                )
                return
            if self.path == "/api/auth/desktop/activate":
                _json_response(
                    self,
                    {
                        "session_token": derive_desktop_pending_token(
                            body["activation_attempt_secret"],
                            body["activation_attempt_id"],
                        ),
                        "activation_attempt_id": body["activation_attempt_id"],
                        "server_id": "server-1",
                        "data_generation": "gen-1",
                        "account_public_id": "acct-1",
                        "device_public_id": "dev-1",
                        "ledger_id": "owner",
                        "expires_at": "2026-10-24T00:00:00Z",
                        "soft_refresh_after": "2026-10-17T00:00:00Z",
                        "activated": True,
                    },
                )
                return
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server_requests: list[dict] = []
    with _Server(Handler) as server:
        pending = pair_product_session(server.origin, "12345678", timeout_seconds=1)
        activated = activate_product_session(
            server.origin,
            pending,
            "tbx-previous-secret",
            timeout_seconds=1,
        )
        revoke_product_session(server.origin, activated.session_token, timeout_seconds=1)

    # The pending value is the client-derived one; the staged TTL is the
    # activation expiry — never a server-minted token.
    assert pending.session.session_token == derive_desktop_pending_token(
        pair_body["pairing_attempt_secret"],
        pair_body["pairing_attempt_id"],
    )
    assert pending.session.expires_at == "2026-07-26T22:20:00Z"
    # Activation keeps the same value and refreshes the expiry metadata.
    assert activated.session_token == pending.session.session_token
    assert activated.expires_at == "2026-10-24T00:00:00Z"

    assert server_requests == [
        {
            "path": "/api/auth/pair",
            "authorization": None,
            "bridge": None,
            "previous": None,
            "body": {
                "pairing_code": "12345678",
                "pairing_attempt_id": pair_body["pairing_attempt_id"],
                "pairing_attempt_secret": pair_body["pairing_attempt_secret"],
                "device_name": "小票夹 Desktop",
                "platform": "desktop",
            },
        },
        {
            "path": "/api/auth/desktop/activate",
            "authorization": None,
            "bridge": None,
            "previous": "tbx-previous-secret",
            "body": {
                "activation_attempt_id": pair_body["pairing_attempt_id"],
                "activation_attempt_secret": pair_body["pairing_attempt_secret"],
            },
        },
        {
            "path": "/desktop/session/revoke",
            "authorization": f"Bearer {activated.session_token}",
            "bridge": "v1",
            "previous": None,
            "body": None,
        },
    ]


def test_activate_omits_previous_header_when_no_predecessor() -> None:
    seen: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            seen.append(self.headers.get("X-Ticketbox-Previous-Session"))
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            _json_response(
                self,
                {
                    "session_token": pending.session.session_token,
                    "activation_attempt_id": pending.activation_attempt_id,
                    "server_id": "server-1",
                    "data_generation": "gen-1",
                    "account_public_id": "acct-1",
                    "device_public_id": "dev-1",
                    "ledger_id": "owner",
                    "expires_at": None,
                    "soft_refresh_after": None,
                    "activated": True,
                },
            )

    attempt_id, attempt_secret = new_activation_attempt()
    pending = PendingProductSession(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        session=ProductSession(
            session_token=derive_desktop_pending_token(attempt_secret, attempt_id),
            account_name="我",
            ledger_id="owner",
            ledger_name="我的小票夹",
            device_name="小票夹 Desktop",
            role="owner",
            expires_at="2026-07-26T22:20:00Z",
        ),
    )
    with _Server(Handler) as server:
        activated = activate_product_session(server.origin, pending, None, timeout_seconds=1)

    assert seen == [None]
    assert activated.expires_at is None


def test_pair_rejects_foreign_or_non_activatable_response() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            _json_response(
                self,
                {
                    "session_token": "tbx_server_minted_foreign_value",
                    "pairing_attempt_id": "12345678-1234-5678-1234-567812345678",
                    "account_name": "我",
                    "ledger_id": "owner",
                    "ledger_name": "我的小票夹",
                    "device_name": "小票夹 Desktop",
                    "role": "owner",
                    "activation_required": True,
                    "activation_expires_at": "2026-07-26T22:20:00Z",
                },
            )

    with _Server(Handler) as server, pytest.raises(ProductDataError, match="合同不完整"):
        pair_product_session(server.origin, "12345678", timeout_seconds=1)


def test_switch_stages_on_target_with_attempt_proof_and_current_bearer() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            server_requests.append({"path": self.path, "authorization": self.headers.get("Authorization")})
            _json_response(
                self,
                {
                    "ledgers": [
                        {"ledger_id": "owner", "name": "我的小票夹", "role": "owner", "is_default": True},
                        {"ledger_id": "family", "name": "家庭账本", "role": "viewer", "is_default": False},
                    ]
                },
            )

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            server_requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": body,
                }
            )
            derived = derive_desktop_pending_token(
                body["activation_attempt_secret"],
                body["activation_attempt_id"],
            )
            _json_response(
                self,
                {
                    "session_token": derived,
                    "server_id": "server-1",
                    "data_generation": "gen-1",
                    "account_public_id": "acct-1",
                    "device_public_id": "dev-1",
                    "expires_at": None,
                    "soft_refresh_after": None,
                    "ledger": {
                        "ledger_id": "family",
                        "name": "家庭账本",
                        "role": "viewer",
                        "is_default": False,
                        "created_at": None,
                        "archived_at": None,
                    },
                    "account_name": "我",
                    "device_name": "小票夹 Desktop",
                    "activation_required": True,
                    "activation_expires_at": "2026-07-26T22:20:00Z",
                },
            )

    server_requests: list[dict] = []
    with _Server(Handler) as server:
        ledgers = list_product_ledgers(server.origin, "tbx-owner-token", timeout_seconds=1)
        pending = switch_product_ledger(
            server.origin,
            "family",
            "tbx-owner-token",
            timeout_seconds=1,
        )

    assert ledgers[1] == {
        "ledger_id": "family",
        "name": "家庭账本",
        "role": "viewer",
        "is_default": False,
    }
    assert pending.session.ledger_id == "family"
    assert pending.session.role == "viewer"
    assert pending.session.expires_at == "2026-07-26T22:20:00Z"
    prepare = server_requests[1]
    assert prepare["path"] == "/api/ledgers/family/switch/prepare"
    assert prepare["authorization"] == "Bearer tbx-owner-token"
    assert prepare["body"] == {
        "activation_attempt_id": pending.activation_attempt_id,
        "activation_attempt_secret": pending.activation_attempt_secret,
    }
    assert pending.session.session_token == derive_desktop_pending_token(
        pending.activation_attempt_secret,
        pending.activation_attempt_id,
    )


def test_gateway_rejects_non_loopback_origins() -> None:
    with pytest.raises(ProductDataError, match="只能连接本机"):
        pair_product_session("https://api.example.test", "12345678", timeout_seconds=1)
    with pytest.raises(ProductDataError, match="只能连接本机"):
        switch_product_ledger("https://api.example.test", "family", "tbx-token", timeout_seconds=1)


def test_error_mapping_preserves_backend_401_and_masks_5xx() -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path.endswith("/switch/prepare"):
                _json_response(
                    self,
                    {"error": "invalid_token", "message": "登录已失效，请重新绑定设备。"},
                    status=401,
                )
                return
            _json_response(self, {"error": "server_error"}, status=500)

    with _Server(Handler) as server:
        with pytest.raises(ProductDataError) as denied:
            switch_product_ledger(server.origin, "family", "tbx-dead-token", timeout_seconds=1)
        with pytest.raises(ProductDataError) as unavailable:
            pair_product_session(server.origin, "12345678", timeout_seconds=1)

    assert denied.value.status_code == 401
    assert denied.value.error == "invalid_token"
    assert denied.value.args[0] == "登录已失效，请重新绑定设备。"
    assert unavailable.value.status_code == 503
    assert unavailable.value.error == "server_error"


def test_activate_rejects_same_value_rotation() -> None:
    attempt_id, attempt_secret = new_activation_attempt()
    derived = derive_desktop_pending_token(attempt_secret, attempt_id)
    pending = PendingProductSession(
        activation_attempt_id=attempt_id,
        activation_attempt_secret=attempt_secret,
        session=ProductSession(
            session_token=derived,
            account_name="我",
            ledger_id="owner",
            ledger_name="我的小票夹",
            device_name="小票夹 Desktop",
            role="owner",
            expires_at="2026-07-26T22:20:00Z",
        ),
    )

    with pytest.raises(ProductDataError) as error:
        activate_product_session(
            "http://127.0.0.1:1",
            pending,
            derived,
            timeout_seconds=1,
        )

    assert error.value.error == "product_identity_rotation_required"
    assert error.value.status_code == 502
