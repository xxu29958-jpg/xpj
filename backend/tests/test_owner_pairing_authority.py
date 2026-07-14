"""Fail-closed Owner Console pairing authority contracts."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, AuthToken, Device, Ledger, LedgerMember, PairingCode
from app.services.owner_console_service import (
    do_create_pairing_code,
    list_console_ledger_choices,
)


def test_owner_pairing_fails_closed_when_owner_authorities_disagree() -> None:
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        assert owner is not None
        assert ledger is not None
        assert db.scalar(
            select(LedgerMember.id)
            .where(LedgerMember.ledger_id == ledger.ledger_id)
            .where(LedgerMember.account_id == owner.id)
            .where(LedgerMember.role == "owner")
            .where(LedgerMember.disabled_at.is_(None))
        ) is not None

        replacement = Account(display_name="projection-only owner")
        db.add(replacement)
        db.flush()
        ledger.owner_account_id = replacement.id
        db.flush()

        def authority_counts() -> tuple[int, int, int]:
            counts = tuple(
                int(db.scalar(select(func.count()).select_from(model)) or 0)
                for model in (PairingCode, Device, AuthToken)
            )
            return counts

        before = authority_counts()

        assert ledger.ledger_id not in {
            choice.ledger_id for choice in list_console_ledger_choices(db)
        }
        with pytest.raises(AppError) as error:
            do_create_pairing_code(
                db,
                ledger_id=ledger.ledger_id,
                account_id=owner.id,
            )

        assert error.value.error == "invalid_request"
        assert error.value.status_code == 409
        assert authority_counts() == before
