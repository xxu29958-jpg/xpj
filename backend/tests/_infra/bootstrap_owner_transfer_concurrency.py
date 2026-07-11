"""Owner-transfer credential revocation race coverage."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

import app.services.invitation_members as invitation_members
from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.identity_service import (
    authenticate_session_token,
    hash_secret,
    lock_bootstrap_owner_transaction,
    new_session_token,
)
from app.services.session_lifecycle_service import revoke_token_value


def _mint_race_token(source_token_value: str) -> str:
    with SessionLocal() as db:
        source = db.scalar(
            select(AuthToken).where(
                AuthToken.token_hash == hash_secret(source_token_value)
            )
        )
        assert source is not None
        device = Device(
            account_id=source.account_id,
            device_name="Owner transfer race device",
            platform="test",
        )
        db.add(device)
        db.flush()
        token_value = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token_value),
                account_id=source.account_id,
                device_id=device.id,
                ledger_id=source.ledger_id,
                scope="app",
            )
        )
        db.commit()
        return token_value


def _create_transfer_target(token_value: str) -> tuple[str, int, int]:
    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(token_value))
        )
        assert token is not None
        target = Account(display_name="Owner transfer race target")
        db.add(target)
        db.flush()
        membership = LedgerMember(
            ledger_id=token.ledger_id,
            account_id=target.id,
            role="member",
        )
        db.add(membership)
        db.commit()
        return token.ledger_id, membership.id, token.account_id


def _attempt_transfer(
    token_value: str,
    ledger_id: str,
    member_id: int,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        auth = authenticate_session_token(db, token_value, {"app"})
        authenticated.set()
        assert proceed.wait(timeout=5)
        try:
            invitation_members.transfer_ledger_owner(
                db,
                ledger_id=ledger_id,
                member_id=member_id,
                requester_account_id=auth.account_id,
                auth=auth,
            )
        except AppError as error:
            db.rollback()
            return error.error
    return "transferred"


def assert_revocation_blocks_pre_authenticated_owner_transfer(
    source_token_value: str,
) -> None:
    token_value = _mint_race_token(source_token_value)
    ledger_id, member_id, original_owner_id = _create_transfer_target(token_value)
    authenticated = threading.Event()
    proceed = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool, SessionLocal() as blocker:
        future = pool.submit(
            _attempt_transfer,
            token_value,
            ledger_id,
            member_id,
            authenticated,
            proceed,
        )
        assert authenticated.wait(timeout=2)
        lock_bootstrap_owner_transaction(blocker)
        assert revoke_token_value(
            blocker,
            token_value=token_value,
            scope="app",
        ) == 1
        proceed.set()
        time.sleep(0.2)
        assert not future.done()
        blocker.commit()
        assert future.result(timeout=5) == "invalid_token"

    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        target = db.get(LedgerMember, member_id)
        assert ledger is not None and ledger.owner_account_id == original_owner_id
        assert target is not None and target.role == "member"
