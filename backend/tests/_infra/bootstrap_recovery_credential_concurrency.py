"""PostgreSQL races for bootstrap credential revocation and ledger switching."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.services.invitation_members as invitation_members
import app.services.ledger_archive_service as ledger_archive_service
import app.services.ledger_service as ledger_service
from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import (
    Account,
    AuthToken,
    Device,
    Invitation,
    Ledger,
    LedgerMember,
    PairingCode,
    UploadLink,
)
from app.services import admin_service, invitation_service
from app.services.admin_service import _devices as admin_devices
from app.services.identity_service import (
    authenticate_session_token,
    create_pairing_code,
    hash_secret,
    lock_bootstrap_owner_transaction,
    rotate_exposed_bootstrap_credentials,
)
from app.services.session_lifecycle_service import revoke_token_value
from app.services.time_service import ensure_utc, now_utc
from app.tenants import AuthContext
from tests._infra.bootstrap_owner_transfer_concurrency import (
    assert_revocation_blocks_pre_authenticated_owner_transfer,
)
from tests._infra.bootstrap_recovery import _VECTOR_SECRET, _enable_http_bootstrap
from tests._infra.bootstrap_recovery_concurrency import _setup_exposed_sessions


def _mint_stale_credential(db: Session, label: str, auth: AuthContext) -> None:
    if label == "pairing":
        create_pairing_code(
            db,
            ledger_id=auth.ledger_id,
            account_id=auth.account_id,
            auth=auth,
        )
        return
    if label == "upload-create":
        admin_service.create_upload_link(
            db,
            ledger_id=auth.ledger_id,
            admin_account_id=auth.account_id,
            default_timezone="Asia/Shanghai",
            ledger_ids={auth.ledger_id},
            auth=auth,
        )
        return
    if label == "upload-rotate":
        public_id = db.scalar(select(UploadLink.public_id).limit(1))
        assert public_id is not None
        admin_service.rotate_upload_link(
            db,
            public_id=public_id,
            ledger_ids={auth.ledger_id},
            auth=auth,
            actor_account_id=auth.account_id,
        )
        return
    invitation_service.create_invitation(
        db,
        ledger_id=auth.ledger_id,
        role="member",
        created_by_account_id=auth.account_id,
        auth=auth,
    )


def _attempt_stale_credential_mint(
    label: str,
    token_value: str,
    scopes: set[str],
    authenticated: threading.Barrier,
    rotation_finished: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, scopes)
        authenticated.wait(timeout=3)
        assert rotation_finished.wait(timeout=5)
        try:
            _mint_stale_credential(db, label, auth)
        except AppError as error:
            db.rollback()
            return error.error
    return "created"


def _assert_credential_counts() -> None:
    with SessionLocal() as db:
        checked_at = now_utc()
        pairings = db.query(PairingCode).all()
        active_pairings = [
            pairing
            for pairing in pairings
            if pairing.used_at is None
            and (ensure_utc(pairing.expires_at) or pairing.expires_at) > checked_at
        ]
        assert len(active_pairings) == 1
        assert all(
            pairing in active_pairings
            or pairing.used_at is not None
            or (ensure_utc(pairing.expires_at) or pairing.expires_at) <= checked_at
            for pairing in pairings
        )
        assert db.query(UploadLink).count() == 1
        assert db.query(Invitation).count() == 0


def _rotate_exposed_credentials(label: str) -> None:
    with SessionLocal() as db:
        rotated = rotate_exposed_bootstrap_credentials(
            db,
            exposed_secret=_VECTOR_SECRET,
            replacement_secret=f"replacement-{label}-secret-with-32-bytes",
        )
        assert rotated is not None


def _assert_rotation_blocks_case(label: str, scope: str) -> None:
    admin_token, app_token = _setup_exposed_sessions()
    token = admin_token if scope == "admin" else app_token
    authenticated = threading.Barrier(2)
    rotation_finished = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _attempt_stale_credential_mint,
            label,
            token,
            {scope},
            authenticated,
            rotation_finished,
        )
        authenticated.wait(timeout=3)
        try:
            _rotate_exposed_credentials(label)
        finally:
            rotation_finished.set()
        assert future.result(timeout=5) == "invalid_token"
    _assert_credential_counts()


def _revoke_session_token(token_value: str) -> None:
    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value))
        )
        assert token is not None
        token.revoked_at = now_utc()
        db.commit()


def _assert_manual_revocation_blocks_invitation() -> None:
    _admin_token, app_token = _setup_exposed_sessions()
    authenticated = threading.Barrier(2)
    revocation_finished = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _attempt_stale_credential_mint,
            "invitation",
            app_token,
            {"app"},
            authenticated,
            revocation_finished,
        )
        authenticated.wait(timeout=3)
        try:
            _revoke_session_token(app_token)
        finally:
            revocation_finished.set()
        assert future.result(timeout=5) == "invalid_token"
    with SessionLocal() as db:
        assert db.query(Invitation).count() == 0


def assert_pre_authenticated_credential_mints_fail_after_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    cases = (
        ("pairing", "app"),
        ("upload-create", "admin"),
        ("upload-rotate", "admin"),
        ("invitation", "app"),
    )
    try:
        for label, scope in cases:
            _assert_rotation_blocks_case(label, scope)
        _assert_manual_revocation_blocks_invitation()
    finally:
        get_settings.cache_clear()


def _attempt_pre_authenticated_mint(
    label: str,
    token_value: str,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, {"app"})
        authenticated.set()
        assert proceed.wait(timeout=5)
        try:
            _mint_stale_credential(db, label, auth)
        except AppError as error:
            db.rollback()
            return error.error
    return "created"


def _assert_token_revocation_blocks_pre_authenticated_mint(token_value: str) -> None:
    authenticated = threading.Event()
    proceed = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool, SessionLocal() as blocker:
        future = pool.submit(
            _attempt_pre_authenticated_mint,
            "invitation",
            token_value,
            authenticated,
            proceed,
        )
        assert authenticated.wait(timeout=2)
        lock_bootstrap_owner_transaction(blocker)
        assert revoke_token_value(blocker, token_value=token_value, scope="app") == 1
        proceed.set()
        time.sleep(0.2)
        assert not future.done()
        blocker.commit()
        assert future.result(timeout=5) == "invalid_token"


def _device_ids_for_token(token_value: str) -> tuple[str, str]:
    with SessionLocal() as db:
        target = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value))
        )
        admin = db.scalar(select(AuthToken).where(AuthToken.scope == "admin"))
        assert target is not None and admin is not None
        target_device = db.get(Device, target.device_id)
        admin_device = db.get(Device, admin.device_id)
        assert target_device is not None and admin_device is not None
        return target_device.public_id, admin_device.public_id


def _assert_device_revocation_blocks_pre_authenticated_mint(
    monkeypatch: pytest.MonkeyPatch,
    token_value: str,
) -> None:
    target_public_id, current_public_id = _device_ids_for_token(token_value)
    revocation_locked = threading.Event()
    release_revocation = threading.Event()
    original_lookup = admin_devices._device_by_public_id

    def gated_lookup(*args: object, **kwargs: object):
        revocation_locked.set()
        assert release_revocation.wait(timeout=5)
        return original_lookup(*args, **kwargs)

    def revoke_device() -> None:
        with SessionLocal() as db:
            admin_service.revoke_device(
                db,
                public_id=target_public_id,
                current_device_public_id=current_public_id,
                auth=None,
                actor_account_id=None,
            )

    authenticated = threading.Event()
    proceed = threading.Event()
    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(admin_devices, "_device_by_public_id", gated_lookup)
        mint = pool.submit(
            _attempt_pre_authenticated_mint,
            "pairing",
            token_value,
            authenticated,
            proceed,
        )
        assert authenticated.wait(timeout=2)
        revoke = pool.submit(revoke_device)
        assert revocation_locked.wait(timeout=2)
        proceed.set()
        time.sleep(0.2)
        assert not mint.done()
        release_revocation.set()
        revoke.result(timeout=5)
        assert mint.result(timeout=5) == "invalid_token"


def assert_ordinary_revocations_serialize_credential_mints(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_value: str,
    device_token_value: str,
) -> None:
    assert_revocation_blocks_pre_authenticated_owner_transfer(token_value)
    _assert_token_revocation_blocks_pre_authenticated_mint(token_value)
    _assert_device_revocation_blocks_pre_authenticated_mint(
        monkeypatch,
        device_token_value,
    )
    with SessionLocal() as db:
        assert db.query(Invitation).count() == 0
        assert db.query(PairingCode).count() == 1


def _attempt_pre_authenticated_switch(
    token_value: str,
    target_ledger_id: str,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, {"app"})
        authenticated.set()
        assert proceed.wait(timeout=5)
        try:
            ledger_service.switch_ledger(
                db,
                auth=auth,
                current_token_value=token_value,
                account_id=auth.account_id,
                device_id=auth.device_id,
                target_ledger_id=target_ledger_id,
            )
        except AppError as error:
            db.rollback()
            return error.error
    return "switched"


def _run_switch_target_race(
    token_value: str,
    target_ledger_id: str,
    mutate_target: Callable[[], None],
    mutation_locked: threading.Event,
    release_mutation: threading.Event,
) -> None:
    authenticated = threading.Event()
    proceed = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        switched = pool.submit(
            _attempt_pre_authenticated_switch,
            token_value,
            target_ledger_id,
            authenticated,
            proceed,
        )
        assert authenticated.wait(timeout=2)
        mutation = pool.submit(mutate_target)
        assert mutation_locked.wait(timeout=2)
        proceed.set()
        time.sleep(0.2)
        assert not switched.done()
        release_mutation.set()
        mutation.result(timeout=5)
        assert switched.result(timeout=5) == "ledger_forbidden"


def _assert_archived_target_rolls_back_switch(
    monkeypatch: pytest.MonkeyPatch,
    token_value: str,
    account_id: int,
) -> None:
    mutation_locked = threading.Event()
    release_mutation = threading.Event()
    original_authorize = ledger_archive_service._authorize_ledger_owner

    def gated_authorize(*args: object, **kwargs: object):
        mutation_locked.set()
        assert release_mutation.wait(timeout=5)
        return original_authorize(*args, **kwargs)

    def archive_target() -> None:
        with SessionLocal() as db:
            assert ledger_service.archive_ledger(
                db,
                ledger_id="tester_1",
                actor_account_id=account_id,
                auth=None,
            )

    with monkeypatch.context() as patch:
        patch.setattr(ledger_archive_service, "_authorize_ledger_owner", gated_authorize)
        _run_switch_target_race(
            token_value,
            "tester_1",
            archive_target,
            mutation_locked,
            release_mutation,
        )


def _create_member_disable_target(account_id: int) -> tuple[str, int, int]:
    with SessionLocal() as db:
        owner = Account(display_name="Switch target owner")
        db.add(owner)
        db.flush()
        ledger_id = "switch_member_disable_target"
        db.add(Ledger(ledger_id=ledger_id, name="Disable target", owner_account_id=owner.id))
        db.flush()
        owner_member = LedgerMember(ledger_id=ledger_id, account_id=owner.id, role="owner")
        target_member = LedgerMember(ledger_id=ledger_id, account_id=account_id, role="member")
        db.add_all((owner_member, target_member))
        db.commit()
        return ledger_id, target_member.id, owner.id


def _assert_disabled_target_rolls_back_switch(
    monkeypatch: pytest.MonkeyPatch,
    token_value: str,
    account_id: int,
) -> None:
    ledger_id, member_id, owner_id = _create_member_disable_target(account_id)
    mutation_locked = threading.Event()
    release_mutation = threading.Event()
    original_require_owner = invitation_members.require_active_owner

    def gated_require_owner(*args: object, **kwargs: object):
        mutation_locked.set()
        assert release_mutation.wait(timeout=5)
        return original_require_owner(*args, **kwargs)

    def disable_target() -> None:
        with SessionLocal() as db:
            invitation_members.disable_member(
                db,
                ledger_id=ledger_id,
                member_id=member_id,
                requester_account_id=owner_id,
                auth=None,
            )

    with monkeypatch.context() as patch:
        patch.setattr(invitation_members, "require_active_owner", gated_require_owner)
        _run_switch_target_race(
            token_value,
            ledger_id,
            disable_target,
            mutation_locked,
            release_mutation,
        )


def assert_switch_revalidates_locked_target_before_default_change(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token_value: str,
) -> None:
    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value))
        )
        assert token is not None
        account_id = token.account_id
        source_token_id = token.id
        source_device_id = token.device_id
    _assert_archived_target_rolls_back_switch(monkeypatch, token_value, account_id)
    _assert_disabled_target_rolls_back_switch(monkeypatch, token_value, account_id)
    with SessionLocal() as db:
        source = db.get(AuthToken, source_token_id)
        assert source is not None and source.revoked_at is None
        assert source.ledger_id == "owner"
        target_tokens = db.scalars(
            select(AuthToken)
            .where(AuthToken.device_id == source_device_id)
            .where(AuthToken.ledger_id.in_(("tester_1", "switch_member_disable_target")))
        )
        assert list(target_tokens) == []
