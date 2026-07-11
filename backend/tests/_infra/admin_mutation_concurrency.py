"""PostgreSQL races for admin device and UploadLink mutations."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember, UploadLink
from app.services import admin_service, invitation_service
from app.services.identity_service import (
    authenticate_session_token,
    hash_secret,
    lock_bootstrap_owner_transaction,
)
from app.services.session_lifecycle_service import (
    revoke_token_value,
    upload_link_expires_at,
)
from app.services.time_service import now_utc
from app.tenants import AuthContext
from tests._infra.identity import TestIdentity

STALE_ADMIN_MUTATION_CASES = (
    "device-rename",
    "device-revoke",
    "device-delete",
    "upload-create",
    "upload-rotate",
    "upload-revoke",
    "upload-extend",
    "upload-limits",
    "upload-delete",
)


def _owner_identity() -> tuple[int, str]:
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
        assert owner is not None
        return owner.id, "owner"


def _seed_mutation_target(label: str) -> str | None:
    if label == "upload-create":
        return None
    owner_id, ledger_id = _owner_identity()
    created_at = now_utc()
    with SessionLocal() as db:
        device = Device(
            account_id=owner_id,
            device_name=f"stale target {label}",
            platform="test",
            created_at=created_at,
            revoked_at=created_at if label == "device-delete" else None,
        )
        db.add(device)
        db.flush()
        if label.startswith("device-"):
            db.add(
                AuthToken(
                    token_hash=hash_secret(f"stale-device-{label}"),
                    account_id=owner_id,
                    device_id=device.id,
                    ledger_id=ledger_id,
                    scope="app",
                    created_at=created_at,
                    revoked_at=created_at if label == "device-delete" else None,
                )
            )
            db.commit()
            return device.public_id
        link = UploadLink(
            token_hash=hash_secret(f"stale-upload-{label}"),
            account_id=owner_id,
            device_id=device.id,
            ledger_id=ledger_id,
            created_at=created_at,
            expires_at=upload_link_expires_at(created_at),
            revoked_at=created_at if label == "upload-delete" else None,
        )
        db.add(link)
        db.commit()
        return link.public_id


def _mutation_snapshot(label: str, public_id: str | None) -> tuple[object, ...]:
    with SessionLocal() as db:
        if label == "upload-create":
            count = db.scalar(select(func.count()).select_from(UploadLink))
            return (int(count or 0),)
        if label.startswith("device-"):
            device = db.scalar(select(Device).where(Device.public_id == public_id))
            assert device is not None
            token_count = db.scalar(
                select(func.count())
                .select_from(AuthToken)
                .where(AuthToken.device_id == device.id)
            )
            return (device.device_name, device.revoked_at, int(token_count or 0))
        link = db.scalar(select(UploadLink).where(UploadLink.public_id == public_id))
        assert link is not None
        count = db.scalar(select(func.count()).select_from(UploadLink))
        return (
            int(count or 0),
            link.revoked_at,
            link.expires_at,
            link.daily_byte_budget,
            link.per_remote_min_interval_seconds,
        )


def _current_device_public_id(auth: AuthContext) -> str:
    with SessionLocal() as db:
        public_id = admin_service.device_public_id(db, auth.device_id)
        assert public_id
        return public_id


def _run_stale_admin_mutation(
    db: Session,
    *,
    label: str,
    auth: AuthContext,
    public_id: str | None,
) -> None:
    scope = {"owner"}
    if label == "device-rename":
        assert public_id is not None
        admin_service.rename_device(
            db,
            public_id=public_id,
            new_name="must not commit",
            auth=auth,
            actor_account_id=auth.account_id,
            ledger_ids=scope,
        )
    elif label == "device-revoke":
        assert public_id is not None
        admin_service.revoke_device(
            db,
            public_id=public_id,
            current_device_public_id=_current_device_public_id(auth),
            auth=auth,
            actor_account_id=auth.account_id,
            ledger_ids=scope,
        )
    elif label == "device-delete":
        assert public_id is not None
        admin_service.delete_device(
            db,
            public_id=public_id,
            current_device_public_id=_current_device_public_id(auth),
            auth=auth,
            actor_account_id=auth.account_id,
            ledger_ids=scope,
        )
    elif label == "upload-create":
        admin_service.create_upload_link(
            db,
            ledger_id="owner",
            admin_account_id=auth.account_id,
            default_timezone="Asia/Shanghai",
            auth=auth,
            ledger_ids=scope,
        )
    else:
        assert public_id is not None
        _run_stale_upload_mutation(db, label=label, auth=auth, public_id=public_id)


def _run_stale_upload_mutation(
    db: Session,
    *,
    label: str,
    auth: AuthContext,
    public_id: str,
) -> None:
    kwargs = {
        "public_id": public_id,
        "auth": auth,
        "actor_account_id": auth.account_id,
        "ledger_ids": {"owner"},
    }
    if label == "upload-rotate":
        admin_service.rotate_upload_link(db, **kwargs)
    elif label == "upload-revoke":
        admin_service.revoke_upload_link(db, **kwargs)
    elif label == "upload-extend":
        admin_service.extend_upload_link(db, **kwargs)
    elif label == "upload-limits":
        admin_service.update_upload_link_limits(
            db,
            daily_byte_budget=4096,
            per_remote_min_interval_seconds=2,
            **kwargs,
        )
    else:
        admin_service.delete_upload_link(db, **kwargs)


def _attempt_revoked_admin_mutation(
    label: str,
    token_value: str,
    public_id: str | None,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, {"admin"})
        authenticated.set()
        assert proceed.wait(timeout=5)
        try:
            _run_stale_admin_mutation(
                db,
                label=label,
                auth=auth,
                public_id=public_id,
            )
        except AppError as error:
            db.rollback()
            return error.error
    return "committed"


def assert_revoked_admin_mutation_is_rejected(
    identity: TestIdentity,
    label: str,
) -> None:
    public_id = _seed_mutation_target(label)
    before = _mutation_snapshot(label, public_id)
    authenticated = threading.Event()
    proceed = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool, SessionLocal() as blocker:
        future = pool.submit(
            _attempt_revoked_admin_mutation,
            label,
            identity.admin_token,
            public_id,
            authenticated,
            proceed,
        )
        assert authenticated.wait(timeout=2)
        lock_bootstrap_owner_transaction(blocker)
        assert (
            revoke_token_value(
                blocker,
                token_value=identity.admin_token,
                scope="admin",
            )
            == 1
        )
        proceed.set()
        blocker.commit()
        assert future.result(timeout=5) == "invalid_token"
    assert _mutation_snapshot(label, public_id) == before


def _seed_transfer_target() -> tuple[str, int, str, datetime]:
    owner_id, _owner_ledger = _owner_identity()
    created_at = now_utc()
    ledger_id = "stale_admin_scope_target"
    with SessionLocal() as db:
        target = Account(display_name="new scoped owner", created_at=created_at)
        db.add(target)
        db.flush()
        ledger = Ledger(
            ledger_id=ledger_id,
            name="stale scope target",
            owner_account_id=owner_id,
            created_at=created_at,
        )
        db.add(ledger)
        db.flush()
        db.add_all(
            [
                LedgerMember(
                    ledger_id=ledger_id,
                    account_id=owner_id,
                    role="owner",
                    created_at=created_at,
                ),
                LedgerMember(
                    ledger_id=ledger_id,
                    account_id=target.id,
                    role="member",
                    created_at=created_at,
                ),
            ]
        )
        device = Device(
            account_id=owner_id,
            device_name="stale scope shortcut",
            platform="ios",
            created_at=created_at,
        )
        db.add(device)
        db.flush()
        link = UploadLink(
            token_hash=hash_secret("stale-scope-upload-link"),
            account_id=owner_id,
            device_id=device.id,
            ledger_id=ledger_id,
            created_at=created_at,
            expires_at=upload_link_expires_at(created_at),
        )
        db.add(link)
        db.commit()
        member_id = db.scalar(
            select(LedgerMember.id).where(
                LedgerMember.ledger_id == ledger_id,
                LedgerMember.account_id == target.id,
            )
        )
        assert member_id is not None
        return ledger_id, member_id, link.public_id, link.expires_at


def _attempt_stale_scope_upload_mutation(
    label: str,
    token_value: str,
    ledger_id: str,
    public_id: str,
    authenticated: threading.Barrier,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, {"admin"})
        authenticated.wait(timeout=3)
        assert proceed.wait(timeout=5)
        try:
            if label == "create":
                admin_service.create_upload_link(
                    db,
                    ledger_id=ledger_id,
                    admin_account_id=auth.account_id,
                    default_timezone="Asia/Shanghai",
                    auth=auth,
                    ledger_ids={ledger_id},
                )
            else:
                admin_service.rotate_upload_link(
                    db,
                    public_id=public_id,
                    auth=auth,
                    actor_account_id=auth.account_id,
                    ledger_ids={ledger_id},
                )
        except AppError as error:
            db.rollback()
            return error.error
    return "committed"


def assert_owner_transfer_invalidates_precomputed_admin_scope(
    identity: TestIdentity,
) -> None:
    ledger_id, member_id, public_id, expires_at = _seed_transfer_target()
    authenticated = threading.Barrier(3)
    proceed = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _attempt_stale_scope_upload_mutation,
                label,
                identity.admin_token,
                ledger_id,
                public_id,
                authenticated,
                proceed,
            )
            for label in ("create", "rotate")
        ]
        authenticated.wait(timeout=3)
        with SessionLocal() as db:
            owner_id = db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))
            assert owner_id is not None
            invitation_service.transfer_ledger_owner(
                db,
                ledger_id=ledger_id,
                member_id=member_id,
                requester_account_id=owner_id,
                auth=None,
            )
        proceed.set()
        assert [future.result(timeout=5) for future in futures] == [
            "invalid_request",
            "invalid_request",
        ]

    with SessionLocal() as db:
        admin = db.scalar(
            select(AuthToken).where(
                AuthToken.token_hash == hash_secret(identity.admin_token)
            )
        )
        link = db.scalar(select(UploadLink).where(UploadLink.public_id == public_id))
        link_count = db.scalar(
            select(func.count())
            .select_from(UploadLink)
            .where(UploadLink.ledger_id == ledger_id)
        )
        assert admin is not None and admin.revoked_at is None
        assert link is not None and link.revoked_at is None
        assert link.expires_at == expires_at
        assert link_count == 1
