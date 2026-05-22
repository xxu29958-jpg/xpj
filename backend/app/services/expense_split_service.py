from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Account, Expense, ExpenseSplit, LedgerAuditLog, LedgerMember
from app.schemas import (
    ExpenseSplitReplaceRequest,
    ExpenseSplitResponse,
    ExpenseSplitsResponse,
)
from app.services.expense_service import EDITABLE_STATUSES, get_expense
from app.services.time_service import now_utc

AUDIT_EXPENSE_SPLITS_REPLACED = "expense_splits_replaced"


@dataclass(frozen=True)
class _SplitMember:
    member_id: int
    account_public_id: str
    account_name: str
    role: str
    disabled_at: datetime | None


def list_expense_splits(db: Session, expense_id: int, tenant_id: str) -> ExpenseSplitsResponse:
    expense = get_expense(db, expense_id, tenant_id)
    return _build_response(db, expense)


def replace_expense_splits(
    db: Session,
    expense_id: int,
    tenant_id: str,
    payload: ExpenseSplitReplaceRequest,
    *,
    actor_account_id: int | None,
) -> ExpenseSplitsResponse:
    expense = get_expense(db, expense_id, tenant_id)
    if expense.status not in EDITABLE_STATUSES:
        raise AppError("expense_not_found", status_code=404)

    member_ids = [item.member_id for item in payload.splits]
    if len(member_ids) != len(set(member_ids)):
        raise AppError("invalid_request", "同一个家庭成员不能重复拆账。", status_code=422)
    members = _members_by_id(
        db,
        tenant_id=tenant_id,
        member_ids=member_ids,
        active_only=True,
    )
    missing_member_ids = sorted(set(member_ids) - set(members))
    if missing_member_ids:
        raise AppError("member_not_found", status_code=404)

    existing = list(
        db.scalars(
            ledger_scoped_select(ExpenseSplit, tenant_id).where(
                ExpenseSplit.expense_id == expense.id
            )
        )
    )
    existing_members = _members_by_id(
        db,
        tenant_id=tenant_id,
        member_ids=[split.member_id for split in existing],
        active_only=False,
    )
    before_snapshot = _audit_snapshot(existing, existing_members)
    for split in existing:
        db.delete(split)
    db.flush()

    now = now_utc()
    new_splits: list[ExpenseSplit] = []
    for position, request_split in enumerate(payload.splits):
        split = ExpenseSplit(
            tenant_id=expense.tenant_id,
            expense_id=expense.id,
            member_id=request_split.member_id,
            position=position,
            amount_cents=request_split.amount_cents,
            note=_clean_note(request_split.note),
            created_at=now,
            updated_at=now,
        )
        new_splits.append(split)
        db.add(split)
    expense.updated_at = now
    _add_split_audit(
        db,
        expense=expense,
        actor_account_id=actor_account_id,
        before_snapshot=before_snapshot,
        after_snapshot=_audit_snapshot(new_splits, members),
    )
    db.commit()
    db.refresh(expense)
    return _build_response(db, expense)


def _members_by_id(
    db: Session,
    *,
    tenant_id: str,
    member_ids: list[int],
    active_only: bool,
) -> dict[int, _SplitMember]:
    if not member_ids:
        return {}
    query = (
        select(LedgerMember, Account)
        .join(Account, Account.id == LedgerMember.account_id)
        .where(LedgerMember.ledger_id == tenant_id)
        .where(LedgerMember.id.in_(set(member_ids)))
    )
    if active_only:
        query = query.where(LedgerMember.disabled_at.is_(None))
    rows = db.execute(query).all()
    return {
        member.id: _SplitMember(
            member_id=member.id,
            account_public_id=account.public_id,
            account_name=account.display_name,
            role=member.role,
            disabled_at=member.disabled_at,
        )
        for member, account in rows
    }


def _members_for_existing_splits(
    db: Session, *, tenant_id: str, splits: list[ExpenseSplit]
) -> dict[int, _SplitMember]:
    return _members_by_id(
        db,
        tenant_id=tenant_id,
        member_ids=[split.member_id for split in splits],
        active_only=False,
    )


def _clean_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _build_response(db: Session, expense: Expense) -> ExpenseSplitsResponse:
    splits = list(
        db.scalars(
            ledger_scoped_select(ExpenseSplit, expense.tenant_id)
            .where(ExpenseSplit.expense_id == expense.id)
            .order_by(ExpenseSplit.position.asc(), ExpenseSplit.id.asc())
        )
    )
    members = _members_for_existing_splits(db, tenant_id=expense.tenant_id, splits=splits)
    total = sum(split.amount_cents for split in splits) if splits else None
    mismatch = (
        expense.amount_cents - total
        if expense.amount_cents is not None and total is not None
        else None
    )
    return ExpenseSplitsResponse(
        expense_id=expense.id,
        parent_amount_cents=expense.amount_cents,
        splits_total_amount_cents=total,
        mismatch_cents=mismatch,
        splits=[_split_response(split, members.get(split.member_id)) for split in splits],
    )


def _split_response(
    split: ExpenseSplit, member: _SplitMember | None
) -> ExpenseSplitResponse:
    return ExpenseSplitResponse(
        public_id=split.public_id,
        position=split.position,
        member_id=split.member_id,
        account_name=member.account_name if member is not None else "已停用成员",
        role=member.role if member is not None else "disabled",
        amount_cents=split.amount_cents,
        note=split.note,
        disabled_at=member.disabled_at if member is not None else None,
        created_at=split.created_at,
        updated_at=split.updated_at,
    )


def _audit_snapshot(
    splits: list[ExpenseSplit], members: dict[int, _SplitMember]
) -> list[dict[str, int | str | None]]:
    return [
        {
            "position": split.position,
            "member_id": split.member_id,
            "account_public_id": (
                members[split.member_id].account_public_id
                if split.member_id in members
                else None
            ),
            "amount_cents": split.amount_cents,
        }
        for split in sorted(splits, key=lambda item: (item.position, item.id or 0))
    ]


def _add_split_audit(
    db: Session,
    *,
    expense: Expense,
    actor_account_id: int | None,
    before_snapshot: list[dict[str, int | str | None]],
    after_snapshot: list[dict[str, int | str | None]],
) -> None:
    db.add(
        LedgerAuditLog(
            ledger_id=expense.tenant_id,
            action=AUDIT_EXPENSE_SPLITS_REPLACED,
            actor_account_id=actor_account_id,
            detail=json.dumps(
                {
                    "expense_public_id": expense.public_id,
                    "before": before_snapshot,
                    "after": after_snapshot,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    )
