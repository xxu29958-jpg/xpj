"""Idempotent debt-goal mutation commands."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Goal
from app.schemas import (
    DebtGoalIntegrityReviewRequest,
    DebtGoalLinksReplaceRequest,
    DebtGoalTargetDateRequest,
    GoalResponse,
)
from app.services.goal_debt_repayment_commands import (
    acknowledge_integrity_review,
    replace_debt_repayment_goal_links,
    set_debt_goal_target_date,
)
from app.services.goal_debt_repayment_core import (
    _canonical_debt_goal_response,
    _debt_goal_response,
    _evaluate_and_maybe_latch,
    _require_debt_repayment_goal,
)
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc

_GOAL_TARGET_TYPE = "goal"
_REPLACE_LINKS_OPERATION = "replace_debt_goal_links"
_REMOVE_VOIDED_OPERATION = "remove_voided_debt_goal_links"
_ACK_REVIEW_OPERATION = "acknowledge_debt_goal_integrity_review"
_SET_TARGET_DATE_OPERATION = "set_debt_goal_target_date"
_ARCHIVE_OPERATION = "archive_debt_repayment_goal"
_RESTORE_OPERATION = "restore_debt_repayment_goal"


def _mutation_claim(
    db: Session,
    *,
    tenant_id: str,
    operation: str,
    public_id: str,
    body: dict[str, object],
    expected_row_version: int,
    idempotency_key: str | None,
) -> ApiIdempotencyKey | None:
    return claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=operation,
        target_id=public_id,
        target_type=_GOAL_TARGET_TYPE,
        body=body,
        expected_row_version=expected_row_version,
    )


def _finish_goal_mutation(
    db: Session,
    *,
    claim: ApiIdempotencyKey,
    tenant_id: str,
    public_id: str,
    persist_achievement: bool,
) -> GoalResponse:
    """Evaluate staged state and atomically commit it with the claim."""
    db.expire_all()
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    evaluation, _ = _evaluate_and_maybe_latch(
        db,
        goal,
        persist=persist_achievement,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_GOAL_TARGET_TYPE,
        resource_id=public_id,
    )
    db.commit()
    db.expire_all()
    current = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    return _debt_goal_response(current, evaluation)


def replace_debt_repayment_goal_links_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalLinksReplaceRequest,
    idempotency_key: str | None,
) -> GoalResponse:
    claim = _mutation_claim(
        db,
        tenant_id=tenant_id,
        operation=_REPLACE_LINKS_OPERATION,
        public_id=public_id,
        body={"debt_public_ids": payload.debt_public_ids},
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    replace_debt_repayment_goal_links(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    return _finish_goal_mutation(
        db,
        claim=claim,
        tenant_id=tenant_id,
        public_id=public_id,
        persist_achievement=True,
    )


def acknowledge_integrity_review_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalIntegrityReviewRequest,
    idempotency_key: str | None,
) -> GoalResponse:
    claim = _mutation_claim(
        db,
        tenant_id=tenant_id,
        operation=_ACK_REVIEW_OPERATION,
        public_id=public_id,
        body={},
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    acknowledge_integrity_review(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    return _finish_goal_mutation(
        db,
        claim=claim,
        tenant_id=tenant_id,
        public_id=public_id,
        persist_achievement=False,
    )


def remove_voided_debt_goal_links_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    idempotency_key: str | None,
) -> GoalResponse:
    """Resolve review by carrying current non-voided links into a new version."""
    claim = _mutation_claim(
        db,
        tenant_id=tenant_id,
        operation=_REMOVE_VOIDED_OPERATION,
        public_id=public_id,
        body={},
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    evaluation, _ = _evaluate_and_maybe_latch(db, goal, persist=False)
    keep = [link.debt_public_id for link in evaluation.linked_debts if link.status != "voided"]
    if not evaluation.needs_review:
        raise AppError(
            "invalid_request",
            "这个目标目前不需要复核。",
            status_code=422,
        )
    if not keep:
        raise AppError(
            "invalid_request",
            "至少需要保留一笔有效欠款；也可以把目标归档。",
            status_code=422,
        )
    replace_debt_repayment_goal_links(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=DebtGoalLinksReplaceRequest(
            expected_row_version=expected_row_version,
            debt_public_ids=keep,
        ),
        commit=False,
    )
    return _finish_goal_mutation(
        db,
        claim=claim,
        tenant_id=tenant_id,
        public_id=public_id,
        persist_achievement=True,
    )


def set_debt_goal_target_date_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalTargetDateRequest,
    idempotency_key: str | None,
) -> GoalResponse:
    claim = _mutation_claim(
        db,
        tenant_id=tenant_id,
        operation=_SET_TARGET_DATE_OPERATION,
        public_id=public_id,
        body={"target_date": (payload.target_date.isoformat() if payload.target_date is not None else None)},
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    set_debt_goal_target_date(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    return _finish_goal_mutation(
        db,
        claim=claim,
        tenant_id=tenant_id,
        public_id=public_id,
        persist_achievement=False,
    )


def archive_debt_repayment_goal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    idempotency_key: str | None,
) -> GoalResponse:
    """Archive one active debt goal with OCC."""
    claim = _mutation_claim(
        db,
        tenant_id=tenant_id,
        operation=_ARCHIVE_OPERATION,
        public_id=public_id,
        body={},
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={
            "status": "archived",
            "archived_at": now,
            "updated_at": now,
        },
        extra_where=(Goal.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        _require_debt_repayment_goal(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
        raise AppError("state_conflict", status_code=409)
    return _finish_goal_mutation(
        db,
        claim=claim,
        tenant_id=tenant_id,
        public_id=public_id,
        persist_achievement=False,
    )


def restore_debt_repayment_goal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    expected_row_version: int,
    idempotency_key: str | None,
) -> GoalResponse:
    """Restore one archived debt goal with OCC."""
    claim = _mutation_claim(
        db,
        tenant_id=tenant_id,
        operation=_RESTORE_OPERATION,
        public_id=public_id,
        body={},
        expected_row_version=expected_row_version,
        idempotency_key=idempotency_key,
    )
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    if goal.status != "archived":
        mark_idempotency_succeeded(
            db,
            claim,
            resource_type=_GOAL_TARGET_TYPE,
            resource_id=public_id,
        )
        db.commit()
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
        )
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={
            "status": "active",
            "archived_at": None,
            "updated_at": now,
        },
        extra_where=(Goal.status == "archived",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)
    return _finish_goal_mutation(
        db,
        claim=claim,
        tenant_id=tenant_id,
        public_id=public_id,
        persist_achievement=False,
    )
