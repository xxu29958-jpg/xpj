"""Non-idempotent debt-goal mutation primitives.

These functions own OCC and transaction staging. Route-facing idempotent
commands compose them with the shared idempotency record in one transaction.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import DebtGoalLink, Goal
from app.schemas import (
    DebtGoalIntegrityReviewRequest,
    DebtGoalLinksReplaceRequest,
    DebtGoalTargetDateRequest,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.goal_debt_repayment_core import (
    _evaluate_and_maybe_latch,
    _require_debt_repayment_goal,
    _resolve_linked_debts,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc


def replace_debt_repayment_goal_links(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalLinksReplaceRequest,
    commit: bool = True,
) -> None:
    """Replace the linked debt set in a new, frozen goal version."""
    resolve_write_capability(db)
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    if goal.status == "archived":
        raise AppError(
            "invalid_request",
            "目标已归档，不能继续修改。",
            status_code=409,
        )
    debts = _resolve_linked_debts(
        db,
        tenant_id=tenant_id,
        debt_public_ids=payload.debt_public_ids,
    )
    now = now_utc()
    new_version = goal.goal_version + 1
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={"goal_version": new_version, "updated_at": now},
        extra_where=(Goal.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_debt_repayment_goal(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
        if current.status != "active":
            raise AppError(
                "invalid_request",
                "目标已归档，不能继续修改。",
                status_code=409,
            )
        raise AppError("state_conflict", status_code=409)
    for debt in debts:
        db.add(
            DebtGoalLink(
                goal_id=goal.id,
                goal_version=new_version,
                debt_id=debt.id,
                created_at=now,
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()


def acknowledge_integrity_review(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalIntegrityReviewRequest,
    commit: bool = True,
) -> None:
    """Acknowledge an achieved version's linked-debt void for audit."""
    resolve_write_capability(db)
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    if goal.status == "archived":
        raise AppError(
            "invalid_request",
            "目标已归档，不能继续修改。",
            status_code=409,
        )
    evaluation, _ = _evaluate_and_maybe_latch(db, goal, persist=False)
    if evaluation.evaluation_state != "achieved" or not evaluation.voided_debt_public_ids:
        raise AppError(
            "invalid_request",
            "没有待确认的债务作废复核（目标须已达成且有被作废的关联欠款）。",
            status_code=422,
        )
    if goal.integrity_reviewed_version == goal.goal_version:
        return
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={
            "integrity_reviewed_version": goal.goal_version,
            "updated_at": now,
        },
        extra_where=(Goal.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_debt_repayment_goal(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
        if current.status != "active":
            raise AppError(
                "invalid_request",
                "目标已归档，不能继续修改。",
                status_code=409,
            )
        raise AppError("state_conflict", status_code=409)
    if commit:
        db.commit()
    else:
        db.flush()


def set_debt_goal_target_date(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalTargetDateRequest,
    commit: bool = True,
) -> None:
    """Set or clear a debt goal payoff deadline without changing its version."""
    resolve_write_capability(db)
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    if goal.status == "archived":
        raise AppError(
            "invalid_request",
            "目标已归档，不能继续修改。",
            status_code=409,
        )
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={"target_date": payload.target_date, "updated_at": now},
        extra_where=(Goal.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_debt_repayment_goal(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
        if current.status != "active":
            raise AppError(
                "invalid_request",
                "目标已归档，不能继续修改。",
                status_code=409,
            )
        raise AppError("state_conflict", status_code=409)
    if commit:
        db.commit()
    else:
        db.flush()
