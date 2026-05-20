"""Owner Console pairing-code creation."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.identity_service import (
    PairingCodeResult,
    create_pairing_code,
)


__all__ = ["PairingCodeResult", "do_create_pairing_code"]


def do_create_pairing_code(
    db: Session, *, ledger_id: str, account_id: int, ttl_minutes: int = 15
) -> PairingCodeResult:
    return create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=ttl_minutes)
