"""Real-DB bootstrap recovery scenarios shared by the pinned test nodes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import app.services.identity_service as identity_service
from app.config import get_settings
from app.database import Base, SessionLocal, engine, init_db
from app.main import app
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    Ledger,
    PairingCode,
    UploadLink,
)
from app.routes import bootstrap as bootstrap_route
from app.services.identity_service import (
    hash_pairing_code,
    hash_secret,
)
from app.services.session_lifecycle_service import (
    derive_bootstrap_admin_token,
    derive_bootstrap_pairing_code,
    derive_bootstrap_upload_key,
)
from app.services.time_service import ensure_utc, now_utc

_VECTOR_SECRET = "ticketbox-bootstrap-vector-2026-07-10"
_VECTOR_ADMIN_TOKEN = "tbx_f1cz5I0IKi0r6iUzmoexescoDH0xYOF7_-R39LpN7lY"
_VECTOR_UPLOAD_KEY = "upl_I8Q7_d0BrxgzKxMlkZFUtd9eFF1xe40zM8dt2h1cyeU"
_VECTOR_PAIRING_CODE = "05747978"


def _enable_http_bootstrap(monkeypatch: pytest.MonkeyPatch, secret: str) -> None:
    monkeypatch.setenv("ENABLE_HTTP_BOOTSTRAP", "true")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", secret)
    get_settings.cache_clear()


def _post_bootstrap(
    client: TestClient,
    *,
    secret: str,
    body: dict[str, str] | None = None,
):
    return client.post(
        "/api/bootstrap/owner",
        headers={"X-Bootstrap-Secret": secret},
        json=body or {},
    )


def _assert_cross_runtime_vector() -> None:
    # PowerShell contract:
    # key/message = UTF-8 secret / exact ASCII context
    # contexts = ticketbox/bootstrap-owner/v1/{admin-token,upload-key,pairing-code}
    # token/link = HMAC-SHA256 -> base64url without '=' -> tbx_/upl_ prefix
    # pairing = unsigned full digest, big-endian, modulo 100_000_000, width 8
    assert derive_bootstrap_admin_token(_VECTOR_SECRET) == _VECTOR_ADMIN_TOKEN
    assert derive_bootstrap_upload_key(_VECTOR_SECRET) == _VECTOR_UPLOAD_KEY
    assert derive_bootstrap_pairing_code(_VECTOR_SECRET) == _VECTOR_PAIRING_CODE


def _assert_committed_bootstrap_credentials() -> None:
    with SessionLocal() as db:
        assert (
            db.query(AuthToken)
            .filter(AuthToken.token_hash == hash_secret(_VECTOR_ADMIN_TOKEN))
            .count()
            == 1
        )
        assert (
            db.query(UploadLink)
            .filter(UploadLink.token_hash == hash_secret(_VECTOR_UPLOAD_KEY))
            .count()
            == 1
        )
        assert (
            db.query(PairingCode)
            .filter(
                PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
            )
            .count()
            == 1
        )
        assert db.get(
            BootstrapSecretConsumption,
            hash_secret(_VECTOR_SECRET),
        ) is not None


def _recover_bootstrap_response(client: TestClient) -> dict[str, object]:
    recovered = _post_bootstrap(
        client,
        secret=_VECTOR_SECRET,
        body={
            "account_name": "ignored retry name",
            "ledger_name": "ignored retry ledger",
        },
    )
    assert recovered.status_code == 200, recovered.text
    body = recovered.json()
    assert body["account_name"] == "Vector Owner"
    assert body["ledger_id"] == "owner"
    assert body["ledger_name"] != "ignored retry ledger"
    assert body["device_name"] == "Vector Windows"
    assert body["admin_token"] == _VECTOR_ADMIN_TOKEN
    assert body["upload_key"] == _VECTOR_UPLOAD_KEY
    assert body["pairing_code"] == _VECTOR_PAIRING_CODE
    return body


def _bootstrap_identity_snapshot() -> dict[str, tuple[tuple[object, ...], ...]]:
    with SessionLocal() as db:
        return {
            "accounts": tuple(db.query(Account.id, Account.display_name).order_by(Account.id).all()),
            "ledgers": tuple(
                db.query(Ledger.id, Ledger.ledger_id, Ledger.owner_account_id)
                .order_by(Ledger.id)
                .all()
            ),
            "devices": tuple(
                db.query(Device.id, Device.public_id, Device.revoked_at)
                .order_by(Device.id)
                .all()
            ),
            "tokens": tuple(
                db.query(
                    AuthToken.id,
                    AuthToken.token_hash,
                    AuthToken.device_id,
                    AuthToken.scope,
                    AuthToken.revoked_at,
                )
                .order_by(AuthToken.id)
                .all()
            ),
            "uploads": tuple(
                db.query(
                    UploadLink.id,
                    UploadLink.token_hash,
                    UploadLink.device_id,
                    UploadLink.revoked_at,
                )
                .order_by(UploadLink.id)
                .all()
            ),
            "pairings": tuple(
                db.query(
                    PairingCode.id,
                    PairingCode.code_hash,
                    PairingCode.used_at,
                    PairingCode.expires_at,
                )
                .order_by(PairingCode.id)
                .all()
            ),
        }


def assert_response_loss_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_cross_runtime_vector()
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()

    def fail_response_materialization(**_kwargs: object) -> None:
        raise RuntimeError("simulated bootstrap response loss")

    try:
        with TestClient(app) as client:
            with monkeypatch.context() as response_loss:
                response_loss.setattr(
                    bootstrap_route,
                    "BootstrapOwnerResponse",
                    fail_response_materialization,
                )
                with pytest.raises(
                    RuntimeError,
                    match="simulated bootstrap response loss",
                ):
                    _post_bootstrap(
                        client,
                        secret=_VECTOR_SECRET,
                        body={
                            "account_name": "Vector Owner",
                            "ledger_name": "Vector Ledger",
                            "device_name": "Vector Windows",
                        },
                    )

            _assert_committed_bootstrap_credentials()
            recovered_body = _recover_bootstrap_response(client)

            repeated = _post_bootstrap(client, secret=_VECTOR_SECRET)
            assert repeated.status_code == 200, repeated.text
            assert repeated.json() == recovered_body

            wrong_secret = _post_bootstrap(client, secret="wrong-after-commit")
            assert wrong_secret.status_code == 401
            assert wrong_secret.json()["error"] == "invalid_bootstrap_secret"
            assert "admin_token" not in wrong_secret.json()
    finally:
        get_settings.cache_clear()


def assert_failure_rolls_back_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "rollback-bootstrap-secret-with-32-byte-minimum"
    _enable_http_bootstrap(monkeypatch, secret)
    Base.metadata.drop_all(bind=engine)
    init_db()

    def fail_pairing_creation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("pairing creation failed")

    try:
        with TestClient(app) as client:
            with monkeypatch.context() as pairing_failure:
                pairing_failure.setattr(
                    identity_service._bootstrap,
                    "_create_pairing_code",
                    fail_pairing_creation,
                )
                with pytest.raises(RuntimeError, match="pairing creation failed"):
                    _post_bootstrap(client, secret=secret)

            with SessionLocal() as db:
                assert db.query(AuthToken).count() == 0
                assert db.query(UploadLink).count() == 0
                assert db.query(PairingCode).count() == 0
                assert db.query(BootstrapSecretConsumption).count() == 0

            retry = _post_bootstrap(client, secret=secret)
            assert retry.status_code == 200, retry.text
            assert retry.json()["admin_token"] == derive_bootstrap_admin_token(secret)
            assert retry.json()["upload_key"] == derive_bootstrap_upload_key(secret)
            assert retry.json()["pairing_code"] == derive_bootstrap_pairing_code(secret)
    finally:
        get_settings.cache_clear()


def assert_expired_pairing_recovery_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()
    advanced_now = now_utc() + timedelta(days=1)
    expired_at = advanced_now - timedelta(seconds=1)

    try:
        with TestClient(app) as client:
            initial = _post_bootstrap(
                client,
                secret=_VECTOR_SECRET,
                body={
                    "account_name": "Vector Owner",
                    "ledger_name": "Vector Ledger",
                    "device_name": "Vector Windows",
                },
            )
            assert initial.status_code == 200, initial.text

            with SessionLocal() as db:
                pairing = db.query(PairingCode).filter(
                    PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
                ).one()
                pairing.expires_at = expired_at
                db.commit()

            with monkeypatch.context() as advanced_clock:
                advanced_clock.setattr(
                    identity_service._bootstrap,
                    "now_utc",
                    lambda: advanced_now,
                )
                recovered = _post_bootstrap(client, secret=_VECTOR_SECRET)

            assert recovered.status_code == 401, recovered.text
            assert recovered.json()["error"] == "invalid_bootstrap_secret"
            assert "pairing_code" not in recovered.json()
            with SessionLocal() as db:
                pairing = db.query(PairingCode).filter(
                    PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
                ).one()
                assert ensure_utc(pairing.expires_at) == expired_at
                assert pairing.used_at is None
                assert db.query(PairingCode).count() == 1
    finally:
        get_settings.cache_clear()


def assert_used_pairing_recovery_finalizes_existing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()

    try:
        with TestClient(app) as client:
            initial = _post_bootstrap(
                client,
                secret=_VECTOR_SECRET,
                body={
                    "account_name": "Vector Owner",
                    "ledger_name": "Vector Ledger",
                    "device_name": "Vector Windows",
                },
            )
            assert initial.status_code == 200, initial.text

            paired = client.post(
                "/api/auth/pair",
                json={
                    "pairing_code": _VECTOR_PAIRING_CODE,
                    "device_name": "Vector Android",
                    "platform": "android",
                },
            )
            assert paired.status_code == 200, paired.text
            paired_token_hash = hash_secret(paired.json()["session_token"])
            before_recovery = _bootstrap_identity_snapshot()

            recovered = _post_bootstrap(client, secret=_VECTOR_SECRET)
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["admin_token"] == _VECTOR_ADMIN_TOKEN
            assert recovered.json()["upload_key"] == _VECTOR_UPLOAD_KEY
            assert recovered.json()["pairing_code"] == _VECTOR_PAIRING_CODE
            assert _bootstrap_identity_snapshot() == before_recovery
            with SessionLocal() as db:
                paired_token = db.query(AuthToken).filter(
                    AuthToken.token_hash == paired_token_hash
                ).one()
                assert paired_token.scope == "app"
                assert paired_token.revoked_at is None
                pairing = db.query(PairingCode).filter(
                    PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
                ).one()
                assert pairing.used_at is not None
                assert db.query(BootstrapSecretConsumption).count() == 1
    finally:
        get_settings.cache_clear()


def assert_revoked_admin_recovery_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()

    try:
        with TestClient(app) as client:
            initial = _post_bootstrap(
                client,
                secret=_VECTOR_SECRET,
                body={
                    "account_name": "Vector Owner",
                    "ledger_name": "Vector Ledger",
                    "device_name": "Vector Windows",
                },
            )
            assert initial.status_code == 200, initial.text

            with SessionLocal() as db:
                admin = db.query(AuthToken).filter(
                    AuthToken.token_hash == hash_secret(_VECTOR_ADMIN_TOKEN)
                ).one()
                admin.revoked_at = now_utc()
                db.commit()

            recovered = _post_bootstrap(client, secret=_VECTOR_SECRET)
            assert recovered.status_code == 401
            assert recovered.json()["error"] == "invalid_bootstrap_secret"
            assert "admin_token" not in recovered.json()
            with SessionLocal() as db:
                assert db.query(AuthToken).count() == 1
                assert db.query(UploadLink).count() == 1
                assert db.query(PairingCode).count() == 1
                assert db.query(BootstrapSecretConsumption).count() == 1
    finally:
        get_settings.cache_clear()
