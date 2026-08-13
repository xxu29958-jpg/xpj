"""PostgreSQL races for bootstrap consumption and recovery lock ordering."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

import app.services.identity_service as identity_service
import app.services.invitation_invites as invitation_invites
from app.config import get_settings
from app.database import SessionLocal, engine, init_db
from app.database_model_registry import Base
from app.errors import AppError
from app.main import app
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    Invitation,
    Ledger,
    PairingCode,
    UploadLink,
)
from app.services import invitation_service
from app.services.identity_service import (
    authenticate_session_token,
    hash_pairing_code,
    hash_secret,
    lock_bootstrap_owner_transaction,
    pair_device,
)
from app.services.time_service import now_utc
from tests._infra.bootstrap_recovery import (
    _VECTOR_ADMIN_TOKEN,
    _VECTOR_PAIRING_CODE,
    _VECTOR_SECRET,
    _enable_http_bootstrap,
    _post_bootstrap,
)
from tests.pairing_test_support import invitation_accept_payload, pairing_payload


def _setup_exposed_sessions() -> tuple[str, str]:
    Base.metadata.drop_all(bind=engine)
    init_db()
    with TestClient(app) as client:
        initial = _post_bootstrap(client, secret=_VECTOR_SECRET)
        assert initial.status_code == 200, initial.text
        paired = client.post(
            "/api/auth/pair",
            json=pairing_payload(
                _VECTOR_PAIRING_CODE,
                device_name="Pre-authenticated owner",
            ),
        )
        assert paired.status_code == 200, paired.text
        return _VECTOR_ADMIN_TOKEN, paired.json()["session_token"]


def _attempt_pairing_while_bootstrap_locked(started: threading.Event) -> str:
    with SessionLocal() as db:
        pairing = db.scalar(
            select(PairingCode).where(
                PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
            )
        )
        assert pairing is not None and pairing.used_at is None
        started.set()
        try:
            pair_device(
                db,
                **pairing_payload(
                    _VECTOR_PAIRING_CODE,
                    device_name="Concurrent Pair",
                ),
                remote_id="bootstrap-lock-pair",
            )
        except AppError as error:
            db.rollback()
            return error.error
    return "created"


def _assert_pairing_consume_revalidates_after_bootstrap_lock() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()
    with TestClient(app) as client:
        assert _post_bootstrap(client, secret=_VECTOR_SECRET).status_code == 200
    started = threading.Event()
    with SessionLocal() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_bootstrap_owner_transaction(blocker)
        future = pool.submit(_attempt_pairing_while_bootstrap_locked, started)
        assert started.wait(timeout=2)
        time.sleep(0.2)
        assert not future.done()
        pairing = blocker.scalar(
            select(PairingCode).where(
                PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
            )
        )
        assert pairing is not None
        pairing.expires_at = now_utc()
        blocker.commit()
        assert future.result(timeout=5) == "invalid_pairing_code"
    with SessionLocal() as db:
        assert db.query(Account).count() == 1
        assert db.query(Device).count() == 1
        assert db.query(AuthToken).count() == 1


def _attempt_invitation_accept_while_bootstrap_locked(
    invite_token: str,
    started: threading.Event,
) -> str:
    with SessionLocal() as db:
        invitation = db.scalar(
            select(Invitation).where(
                Invitation.token_hash == hash_secret(invite_token)
            )
        )
        assert invitation is not None and invitation.revoked_at is None
        started.set()
        request = invitation_accept_payload(
            invite_token,
            account_name="Concurrent Invitee",
            device_name="Concurrent Invite Device",
        )
        try:
            invitation_service.accept_invitation(
                db,
                invite_token=invite_token,
                account_name="Concurrent Invitee",
                device_name="Concurrent Invite Device",
                platform="android",
                enrollment_attempt_id=request["enrollment_attempt_id"],
                enrollment_attempt_secret=request["enrollment_attempt_secret"],
            )
        except AppError as error:
            db.rollback()
            return error.error
    return "created"


def _assert_invitation_accept_revalidates_after_bootstrap_lock() -> None:
    _admin_token, app_token = _setup_exposed_sessions()
    with SessionLocal() as db:
        auth = authenticate_session_token(db, app_token, {"app"})
        created = invitation_service.create_invitation(
            db,
            ledger_id=auth.ledger_id,
            role="member",
            created_by_account_id=auth.account_id,
            auth=auth,
        )
        invitation_id = db.scalar(
            select(Invitation.id).where(
                Invitation.token_hash == hash_secret(created.invite_token)
            )
        )
        assert invitation_id is not None
    started = threading.Event()
    with SessionLocal() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_bootstrap_owner_transaction(blocker)
        future = pool.submit(
            _attempt_invitation_accept_while_bootstrap_locked,
            created.invite_token,
            started,
        )
        assert started.wait(timeout=2)
        time.sleep(0.2)
        assert not future.done()
        invitation = blocker.get(Invitation, invitation_id)
        assert invitation is not None
        invitation.revoked_at = now_utc()
        blocker.commit()
        assert future.result(timeout=5) == "invitation_invalid"
    with SessionLocal() as db:
        invitation = db.get(Invitation, invitation_id)
        assert invitation is not None and invitation.used_at is None
        assert db.query(Account).count() == 1
        assert db.query(Device).count() == 2
        assert db.query(AuthToken).count() == 2


def assert_consumers_revalidate_after_bootstrap_lock() -> None:
    _assert_pairing_consume_revalidates_after_bootstrap_lock()
    _assert_invitation_accept_revalidates_after_bootstrap_lock()


def _recover_bootstrap(started: threading.Event):
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        started.set()
        return identity_service.bootstrap_owner(
            db,
            bootstrap_secret=_VECTOR_SECRET,
        )


def _assert_recovery_waits_for_pairing_consumption() -> None:
    started = threading.Event()
    with SessionLocal() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute(text("SET LOCAL lock_timeout = '3s'"))
        pairing = blocker.scalar(
            select(PairingCode)
            .where(PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE))
            .with_for_update()
        )
        assert pairing is not None
        pairing.used_at = now_utc()
        blocker.flush()
        recovery = pool.submit(_recover_bootstrap, started)
        assert started.wait(timeout=2)
        time.sleep(0.2)
        blocker.commit()
        assert recovery.result(timeout=5).admin_token == _VECTOR_ADMIN_TOKEN


def _assert_recovery_does_not_lock_auth_before_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials_loaded = threading.Event()
    continue_recovery = threading.Event()
    original_loader = identity_service._bootstrap._load_completed_bootstrap_identity

    def gated_identity_loader(*args: object, **kwargs: object):
        credentials_loaded.set()
        assert continue_recovery.wait(timeout=5)
        return original_loader(*args, **kwargs)

    with monkeypatch.context() as lock_order_patch:
        lock_order_patch.setattr(
            identity_service._bootstrap,
            "_load_completed_bootstrap_identity",
            gated_identity_loader,
        )
        started = threading.Event()
        with SessionLocal() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
            blocker.execute(text("SET LOCAL lock_timeout = '750ms'"))
            admin = blocker.scalar(
                select(AuthToken).where(
                    AuthToken.token_hash == hash_secret(_VECTOR_ADMIN_TOKEN)
                )
            )
            assert admin is not None
            device = blocker.scalar(
                select(Device).where(Device.id == admin.device_id).with_for_update()
            )
            assert device is not None
            recovery = pool.submit(_recover_bootstrap, started)
            lock_error: SQLAlchemyError | None = None
            try:
                assert started.wait(timeout=2)
                assert credentials_loaded.wait(timeout=2)
                blocker.execute(
                    update(AuthToken)
                    .where(AuthToken.id == admin.id)
                    .values(revoked_at=now_utc())
                    .execution_options(synchronize_session=False)
                )
            except SQLAlchemyError as exc:
                lock_error = exc
                blocker.rollback()
            finally:
                continue_recovery.set()
            assert recovery.result(timeout=5).admin_token == _VECTOR_ADMIN_TOKEN
            blocker.rollback()
    assert lock_error is None, (
        "recovery retained an AuthToken row lock while another transaction "
        f"held Device: {lock_error!r}"
    )


def assert_concurrent_bootstrap_recovery_lock_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    monkeypatch.setattr(
        invitation_invites,
        "assert_bootstrap_sensitive_mutation_allowed",
        lambda *args, **kwargs: None,
    )
    Base.metadata.drop_all(bind=engine)
    init_db()
    try:
        with TestClient(app) as client:
            initial = _post_bootstrap(client, secret=_VECTOR_SECRET)
            assert initial.status_code == 200, initial.text
        _assert_recovery_waits_for_pairing_consumption()
        _assert_recovery_does_not_lock_auth_before_device(monkeypatch)
        assert_consumers_revalidate_after_bootstrap_lock()
    finally:
        get_settings.cache_clear()


def _bootstrap_distinct_secret(secret: str, barrier: threading.Barrier) -> str:
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout = '3s'"))
        barrier.wait(timeout=2)
        try:
            identity_service.bootstrap_owner(db, bootstrap_secret=secret)
        except AppError as error:
            db.rollback()
            return error.error
    return "created"


def assert_distinct_bootstrap_secrets_create_one_identity() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    barrier = threading.Barrier(2)
    secrets = (
        "first-distinct-bootstrap-secret-with-32-bytes",
        "second-distinct-bootstrap-secret-with-32-bytes",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(
            pool.submit(_bootstrap_distinct_secret, secret, barrier)
            for secret in secrets
        )
        outcomes = tuple(future.result(timeout=5) for future in futures)
    assert sorted(outcomes) == ["bootstrap_already_initialized", "created"]
    with SessionLocal() as db:
        assert db.query(Account).count() == 1
        assert db.query(Ledger).count() == 1
        assert db.query(Device).count() == 1
        assert db.query(AuthToken).count() == 1
        assert db.query(UploadLink).count() == 1
        assert db.query(PairingCode).count() == 1
        assert db.query(BootstrapSecretConsumption).count() == 1
