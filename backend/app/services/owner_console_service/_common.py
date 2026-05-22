"""Shared low-level helpers for the owner_console_service package.

These have no dependency on any sibling submodule. New domain submodules
should depend on this module, never the other way around.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Expense, UploadLink
from app.services.ledger_service import list_managed_ledgers_for_account

logger = logging.getLogger(__name__)


OWNER_CONSOLE_TIMEZONE = "Asia/Shanghai"


def _amount_yuan(amount_cents: int) -> str:
    return f"{int(amount_cents) / 100:.2f}"


def get_owner_account_id(db: Session) -> int | None:
    account = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
    return account.id if account else None


def _owner_ledger_ids(db: Session) -> list[str]:
    owner_id = get_owner_account_id(db)
    if owner_id is None:
        return []
    return [row.ledger_id for row in list_managed_ledgers_for_account(db, account_id=owner_id)]


def _expense_status_count(db: Session, *, tenant_ids: set[str], status: str) -> int:
    if not tenant_ids:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id.in_(tenant_ids), Expense.status == status)
        )
        or 0
    )


def _active_upload_link_count(db: Session, *, ledger_ids: set[str]) -> int:
    if not ledger_ids:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(UploadLink)
            .where(UploadLink.ledger_id.in_(ledger_ids), UploadLink.revoked_at.is_(None))
        )
        or 0
    )
