from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, Device, Ledger, LedgerMember
from app.services.identity_service import authenticate_session_token
from app.services.session_credential_lock import (
    lock_and_revalidate_credential_mint_context,
)
from app.services.time_service import now_utc


def _app_token(identity) -> str:
    return identity.app_headers["Authorization"].removeprefix("Bearer ")


def test_lock_revalidation_refreshes_display_metadata_without_killing_session(identity) -> None:
    token = _app_token(identity)
    with SessionLocal() as db:
        stale = authenticate_session_token(db, token, {"app"})

    with SessionLocal() as db:
        account = db.get(Account, stale.account_id)
        device = db.get(Device, stale.device_id)
        ledger = db.query(Ledger).filter(Ledger.ledger_id == stale.ledger_id).one()
        assert account is not None and device is not None and ledger is not None
        account.display_name = "更新后的成员名"
        device.device_name = "更新后的设备名"
        ledger.name = "更新后的账本名"
        db.commit()

    with SessionLocal() as db:
        refreshed = lock_and_revalidate_credential_mint_context(db, stale)
        assert refreshed is not None
        assert refreshed.account_name == "更新后的成员名"
        assert refreshed.device_name == "更新后的设备名"
        assert refreshed.ledger_name == "更新后的账本名"


def test_lock_revalidation_classifies_lost_ledger_authority_as_403(identity) -> None:
    token = _app_token(identity)
    with SessionLocal() as db:
        stale = authenticate_session_token(db, token, {"app"})

    with SessionLocal() as db:
        membership = db.query(LedgerMember).filter(
            LedgerMember.ledger_id == stale.ledger_id,
            LedgerMember.account_id == stale.account_id,
        ).one()
        membership.disabled_at = now_utc()
        db.commit()

    with SessionLocal() as db, pytest.raises(AppError) as raised:
        lock_and_revalidate_credential_mint_context(db, stale)

    assert raised.value.error == "ledger_forbidden"
    assert raised.value.status_code == 403
