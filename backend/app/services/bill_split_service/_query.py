"""Read-only invitation lookups: list_sent / list_inbox / get_invitation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import BillSplitInvitation, Expense

_INVITATION_STATUSES = frozenset({"invited", "accepted", "rejected", "cancelled", "expired"})


def list_sent(
    db: Session, *, sender_account_id: int, sender_ledger_id: str, limit: int = 50
) -> list[BillSplitInvitation]:
    """Sender view — ledger-scoped (sender_ledger_id is sender's current
    ledger, not invitation.receiver_ledger_id)."""
    rows = db.scalars(
        select(BillSplitInvitation)
        .where(BillSplitInvitation.sender_account_id == sender_account_id)
        .where(BillSplitInvitation.sender_ledger_id == sender_ledger_id)
        .order_by(BillSplitInvitation.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def list_sent_for_expense(
    db: Session, *, sender_account_id: int, expense_id: int, limit: int = 50
) -> list[BillSplitInvitation]:
    """Invitations this sender created from one specific source expense.

    Used by the /web edit-page 发起卡 to list the invitations already sent
    *from this bill* (``list_sent`` is ledger-scoped over every expense).
    Sender-account-scoped so it cannot surface another account's rows.
    """
    rows = db.scalars(
        select(BillSplitInvitation)
        .where(BillSplitInvitation.sender_account_id == sender_account_id)
        .where(BillSplitInvitation.sender_expense_id == expense_id)
        .order_by(BillSplitInvitation.created_at.desc())
        .limit(limit)
    )
    return list(rows)


def list_inbox(
    db: Session, *, receiver_account_id: int, status: str | None = None, limit: int = 50
) -> list[BillSplitInvitation]:
    """Receiver view — **account-scoped, NOT ledger-scoped**. Receiver's
    inbox is the same no matter which ledger they're currently viewing,
    because invitations are not yet bound to a target ledger when they
    arrive."""
    statement = select(BillSplitInvitation).where(
        BillSplitInvitation.receiver_account_id == receiver_account_id
    )
    if status is not None:
        status_value = status.strip().lower()
        if status_value not in _INVITATION_STATUSES:
            raise AppError("split_status_invalid", "Unsupported invitation status.", status_code=400)
        statement = statement.where(BillSplitInvitation.status == status_value)
    rows = db.scalars(statement.order_by(BillSplitInvitation.created_at.desc()).limit(limit))
    return list(rows)


def get_invitation(db: Session, public_id: str) -> BillSplitInvitation:
    inv = db.scalar(
        select(BillSplitInvitation).where(BillSplitInvitation.public_id == public_id)
    )
    if inv is None:
        raise AppError("invitation_not_found", status_code=404)
    return inv


def parent_expense_home_currency_code(db: Session, *, expense_id: int, ledger_id: str) -> str | None:
    """父账单的冻结 home 币种码（遗留 P1-2：/web 拆账解析/渲染口径的 record 权威来源；
    路由不直连模型）。父行缺失/跨账本 → None（调用方落 env 兜底，随后 create 自带
    not-found 错误路径）。"""
    return db.scalar(
        select(Expense.home_currency_code).where(
            Expense.id == expense_id,
            Expense.tenant_id == ledger_id,
        )
    )
