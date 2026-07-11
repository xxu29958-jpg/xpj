"""Revoked pre-authenticated owner credentials cannot commit later mutations."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.services.invitation_members as invitation_members
from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, Invitation, Ledger, LedgerMember
from app.services import invitation_service, ledger_service
from app.services.identity_service import (
    authenticate_session_token,
    lock_bootstrap_owner_transaction,
)
from app.services.session_lifecycle_service import revoke_token_value
from app.services.time_service import now_utc
from app.tenants import AuthContext
from tests._infra.identity import TestIdentity

REVOKED_OWNER_MUTATION_CASES = (
    "create-ledger",
    "revoke-invitation",
    "update-member-role",
    "disable-member",
    "archive-ledger",
    "unarchive-ledger",
)


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner_id = db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))
        assert owner_id is not None
        return owner_id


def _setup_mutation_target(label: str) -> int | str | None:
    if label == "create-ledger" or label.startswith(("archive-", "unarchive-")):
        return None
    owner_id = _owner_account_id()
    with SessionLocal() as db:
        if label == "revoke-invitation":
            created = invitation_service.create_invitation(
                db,
                ledger_id="tester_1",
                role="member",
                created_by_account_id=owner_id,
                auth=None,
            )
            return created.summary.public_id
        account = Account(display_name=f"Mutation target: {label}")
        db.add(account)
        db.flush()
        member = LedgerMember(
            ledger_id="tester_1",
            account_id=account.id,
            role="member",
        )
        db.add(member)
        db.commit()
        return member.id


def _create_ledger(db: Session, auth: AuthContext) -> None:
    ledger_service.create_ledger(
        db,
        account_id=auth.account_id,
        name="Stale credential ledger",
        auth=auth,
    )


def _revoke_invitation(db: Session, auth: AuthContext, target: int | str | None) -> None:
    assert isinstance(target, str)
    invitation_service.revoke_invitation(
        db,
        ledger_id=auth.ledger_id,
        public_id=target,
        actor_account_id=auth.account_id,
        auth=auth,
    )


def _update_member(db: Session, auth: AuthContext, target: int | str | None) -> None:
    assert isinstance(target, int)
    invitation_members.update_member_role(
        db,
        ledger_id=auth.ledger_id,
        member_id=target,
        requester_account_id=auth.account_id,
        role="viewer",
        auth=auth,
    )


def _disable_member(db: Session, auth: AuthContext, target: int | str | None) -> None:
    assert isinstance(target, int)
    invitation_members.disable_member(
        db,
        ledger_id=auth.ledger_id,
        member_id=target,
        requester_account_id=auth.account_id,
        auth=auth,
    )


def _change_ledger_archive_state(db: Session, auth: AuthContext, *, archive: bool) -> None:
    operation = ledger_service.archive_ledger if archive else ledger_service.unarchive_ledger
    operation(
        db,
        ledger_id=auth.ledger_id,
        actor_account_id=auth.account_id,
        auth=auth,
    )


def _run_owner_mutation(
    db: Session,
    *,
    label: str,
    auth: AuthContext,
    target: int | str | None,
) -> None:
    if label == "create-ledger":
        _create_ledger(db, auth)
    elif label == "revoke-invitation":
        _revoke_invitation(db, auth, target)
    elif label == "update-member-role":
        _update_member(db, auth, target)
    elif label == "disable-member":
        _disable_member(db, auth, target)
    else:
        _change_ledger_archive_state(db, auth, archive=label == "archive-ledger")


def _attempt_stale_owner_mutation(
    label: str,
    token_value: str,
    target: int | str | None,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, {"admin", "app"})
        authenticated.set()
        assert proceed.wait(timeout=5)
        try:
            _run_owner_mutation(db, label=label, auth=auth, target=target)
        except AppError as error:
            db.rollback()
            return error.error
    return "committed"


def _assert_mutation_did_not_commit(
    label: str,
    target: int | str | None,
    *,
    ledger_count_before: int,
) -> None:
    with SessionLocal() as db:
        if label == "create-ledger":
            assert db.scalar(select(func.count()).select_from(Ledger)) == ledger_count_before
            return
        if label == "revoke-invitation":
            assert isinstance(target, str)
            invitation = db.scalar(select(Invitation).where(Invitation.public_id == target))
            assert invitation is not None and invitation.revoked_at is None
            return
        if label in {"update-member-role", "disable-member"}:
            assert isinstance(target, int)
            member = db.get(LedgerMember, target)
            assert member is not None and member.role == "member" and member.disabled_at is None
            return
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "tester_1"))
        assert ledger is not None
        if label == "archive-ledger":
            assert ledger.archived_at is None
        else:
            assert ledger.archived_at is not None


def assert_revoked_pre_authenticated_owner_mutation_is_rejected(
    identity: TestIdentity,
    label: str,
) -> None:
    token_value = identity.admin_token if label == "create-ledger" else identity.tenant_app_token
    scope = "admin" if label == "create-ledger" else "app"
    target = _setup_mutation_target(label)
    with SessionLocal() as db:
        ledger_count_before = db.scalar(select(func.count()).select_from(Ledger)) or 0

    authenticated = threading.Event()
    proceed = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool, SessionLocal() as blocker:
        future = pool.submit(
            _attempt_stale_owner_mutation,
            label,
            token_value,
            target,
            authenticated,
            proceed,
        )
        assert authenticated.wait(timeout=2)
        lock_bootstrap_owner_transaction(blocker)
        if label == "unarchive-ledger":
            ledger = blocker.scalar(select(Ledger).where(Ledger.ledger_id == "tester_1"))
            assert ledger is not None
            ledger.archived_at = now_utc()
        assert revoke_token_value(blocker, token_value=token_value, scope=scope) == 1
        proceed.set()
        time.sleep(0.2)
        assert not future.done()
        blocker.commit()
        assert future.result(timeout=5) == "invalid_token"

    _assert_mutation_did_not_commit(
        label,
        target,
        ledger_count_before=ledger_count_before,
    )
