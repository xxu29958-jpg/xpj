"""PostgreSQL races for ledger-switch target revalidation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

import app.services.invitation_members as invitation_members
import app.services.ledger_archive_service as ledger_archive_service
import app.services.ledger_service as ledger_service
from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, AuthToken, Ledger, LedgerMember
from app.services.identity_service import (
    authenticate_session_principal,
    hash_secret,
)


def _attempt_pre_authenticated_switch(
    token_value: str,
    target_ledger_id: str,
    authenticated: threading.Event,
    proceed: threading.Event,
) -> str:
    with SessionLocal() as db:
        principal = authenticate_session_principal(db, token_value, {"app"})
        authenticated.set()
        assert proceed.wait(timeout=5)
        try:
            ledger_service.switch_ledger(
                db,
                principal=principal,
                current_token_value=token_value,
                account_id=principal.account_id,
                device_id=principal.device_id,
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
        db.add(
            Ledger(
                ledger_id=ledger_id,
                name="Disable target",
                owner_account_id=owner.id,
            )
        )
        db.flush()
        owner_member = LedgerMember(
            ledger_id=ledger_id,
            account_id=owner.id,
            role="owner",
        )
        target_member = LedgerMember(
            ledger_id=ledger_id,
            account_id=account_id,
            role="member",
        )
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
            .where(
                AuthToken.ledger_id.in_(
                    ("tester_1", "switch_member_disable_target")
                )
            )
        )
        assert list(target_tokens) == []
