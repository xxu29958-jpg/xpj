"""Web presentation model for one expense's household split facts."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.routes.web_common import _amount_yuan
from app.services.expense_split_service import (
    list_active_split_members,
    list_expense_splits,
)


def web_split_rows(
    db: Session,
    expense_id: int,
    ledger_id: str,
    *,
    currency_code: str,
) -> dict:
    response = list_expense_splits(db, expense_id, ledger_id)
    mismatch_cents = response.mismatch_cents
    reconcile_state = (
        "none"
        if response.splits_total_amount_cents is None
        else "unknown"
        if mismatch_cents is None
        else "partial"
        if mismatch_cents > 0
        else "overallocated"
        if mismatch_cents < 0
        else "balanced"
    )
    rows = [
        {
            "public_id": split.public_id,
            "member_id": split.member_id,
            "account_name": split.account_name,
            "role": split.role,
            "amount_yuan": _amount_yuan(split.amount_cents, currency_code),
            "note": split.note or "",
            "disabled": split.disabled_at is not None,
            "errors": {},
        }
        for split in response.splits
    ]
    rows.extend(
        {
            "public_id": "",
            "member_id": "",
            "amount_yuan": "",
            "note": "",
            "disabled": False,
            "errors": {},
        }
        for _ in range(3)
    )
    return {
        "parent_amount_yuan": _amount_yuan(response.parent_amount_cents, currency_code),
        "total_yuan": _amount_yuan(response.splits_total_amount_cents, currency_code),
        "reconcile_delta_yuan": _amount_yuan(
            abs(mismatch_cents) if mismatch_cents is not None else None,
            currency_code,
        ),
        "reconcile_state": reconcile_state,
        "rows": rows,
    }


def web_split_members(db: Session, ledger_id: str) -> list[dict]:
    return list_active_split_members(db, tenant_id=ledger_id)
