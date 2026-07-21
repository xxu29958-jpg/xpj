"""Debt-repayment goal evaluation, response projection, and read queries.

The current ``goal_version`` owns a frozen debt-link set. Evaluation derives each
linked debt's live fold without mutating debt state, and achievement is latched
only when the caller explicitly enables persistence.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import ApiIdempotencyKey, Debt, DebtGoalLink, Goal
from app.schemas import (
    DebtGoalLinkView,
    DebtRepaymentEvaluation,
    GoalCreateRequest,
    GoalResponse,
)
from app.services.debt_service import compute_remaining, derive_status
from app.services.goal_debt_repayment_kpi import external_payoff_kpi
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.time_service import now_utc

GOAL_TYPE = "debt_repayment"
_GOAL_TARGET_TYPE = "goal"
_CREATE_OPERATION = "create_debt_repayment_goal"


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 80:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _require_at_least_one_debt() -> None:
    raise AppError(
        "invalid_request",
        "还债目标至少需要关联一笔欠款。",
        status_code=422,
    )


def _resolve_linked_debts(
    db: Session,
    *,
    tenant_id: str,
    debt_public_ids: list[str] | None,
) -> list[Debt]:
    """Resolve, deduplicate, and tenant-scope the requested debts."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in debt_public_ids or []:
        public_id = (raw or "").strip()
        if public_id and public_id not in seen:
            seen.add(public_id)
            cleaned.append(public_id)
    if not cleaned:
        _require_at_least_one_debt()
    rows = list(db.scalars(ledger_scoped_select(Debt, tenant_id).where(Debt.public_id.in_(cleaned))))
    by_public_id = {debt.public_id: debt for debt in rows}
    for public_id in cleaned:
        if public_id not in by_public_id:
            raise AppError("debt_not_found", status_code=404)
    return [by_public_id[public_id] for public_id in cleaned]


def _require_debt_repayment_goal(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> Goal:
    goal = db.scalar(ledger_scoped_select(Goal, tenant_id).where(Goal.public_id == public_id).limit(1))
    if goal is None:
        raise AppError("goal_not_found", status_code=404)
    if goal.goal_type != GOAL_TYPE:
        raise AppError("invalid_request", "该目标不是还债目标。", status_code=422)
    return goal


def _current_version_debts(db: Session, goal: Goal) -> list[Debt]:
    statement = (
        select(Debt)
        .join(DebtGoalLink, DebtGoalLink.debt_id == Debt.id)
        .where(DebtGoalLink.goal_id == goal.id)
        .where(DebtGoalLink.goal_version == goal.goal_version)
        .order_by(DebtGoalLink.id.asc())
    )
    return list(db.scalars(statement))


def _evaluate_links(
    db: Session,
    goal: Goal,
) -> tuple[list[DebtGoalLinkView], list[Debt], list[str], bool, bool]:
    """Fold current-version debts into views and evaluation rollup flags."""
    debts = _current_version_debts(db, goal)
    link_views: list[DebtGoalLinkView] = []
    voided_public_ids: list[str] = []
    non_voided_debts: list[Debt] = []
    any_voided = False
    all_cleared = bool(debts)
    for debt in debts:
        remaining = compute_remaining(db, debt)
        status = derive_status(debt, remaining)
        if status == "voided":
            any_voided = True
            voided_public_ids.append(debt.public_id)
        else:
            non_voided_debts.append(debt)
        if status != "cleared":
            all_cleared = False
        link_views.append(
            DebtGoalLinkView(
                debt_public_id=debt.public_id,
                status=status,
                direction=debt.direction,
                counterparty_type=debt.counterparty_type,
                counterparty_label=debt.counterparty_label,
                principal_amount_cents=int(debt.principal_amount_cents),
                remaining_amount_cents=remaining,
                home_currency_code=debt.home_currency_code,
            )
        )
    return (
        link_views,
        non_voided_debts,
        voided_public_ids,
        any_voided,
        all_cleared,
    )


def _evaluate_and_maybe_latch(
    db: Session,
    goal: Goal,
    *,
    persist: bool,
) -> tuple[DebtRepaymentEvaluation, bool]:
    """Evaluate the current link set and optionally latch a fresh achievement."""
    now = now_utc()
    (
        link_views,
        non_voided_debts,
        voided_public_ids,
        any_voided,
        all_cleared,
    ) = _evaluate_links(db, goal)

    already_latched = goal.achieved_version == goal.goal_version
    if already_latched:
        state = "achieved"
    elif any_voided:
        state = "not_evaluable"
    elif all_cleared:
        state = "achieved"
    else:
        state = "in_progress"

    latched = False
    if persist and state == "achieved" and not already_latched:
        goal.achieved_at = now
        goal.achieved_version = goal.goal_version
        latched = True

    integrity_acknowledged = goal.integrity_reviewed_version == goal.goal_version
    needs_review = any_voided and not (state == "achieved" and integrity_acknowledged)

    kpi = external_payoff_kpi(
        db,
        non_voided_debts,
        now=now,
        target_date=goal.target_date,
    )
    evaluation = DebtRepaymentEvaluation(
        goal_version=goal.goal_version,
        evaluation_state=state,
        needs_review=needs_review,
        achieved_at=goal.achieved_at,
        achieved_version=goal.achieved_version,
        linked_debts=link_views,
        voided_debt_public_ids=voided_public_ids,
        tracking_days=kpi.tracking_days,
        projected_payoff_date=kpi.projected_payoff_date,
        target_date=kpi.target_date,
        three_state=kpi.three_state,
        days_since_last_activity=kpi.days_since_last_activity,
    )
    return evaluation, latched


def _debt_goal_response(
    goal: Goal,
    evaluation: DebtRepaymentEvaluation,
) -> GoalResponse:
    """Project a debt goal without spending-limit fields."""
    return GoalResponse(
        public_id=goal.public_id,
        ledger_id=goal.tenant_id,
        name=goal.name,
        goal_type=goal.goal_type,
        period=goal.period,
        month=None,
        category=None,
        target_amount_cents=None,
        spent_amount_cents=None,
        remaining_amount_cents=None,
        progress_percent=None,
        progress_state=evaluation.evaluation_state,
        status=goal.status,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        row_version=goal.row_version,
        archived_at=goal.archived_at,
        debt_repayment=evaluation,
    )


def build_debt_repayment_goal_response(
    db: Session,
    goal: Goal,
    *,
    persist_achievement: bool,
) -> GoalResponse:
    """Evaluate, optionally persist a fresh latch, and serialize one goal."""
    evaluation, latched = _evaluate_and_maybe_latch(
        db,
        goal,
        persist=persist_achievement,
    )
    if latched:
        db.commit()
    return _debt_goal_response(goal, evaluation)


def _canonical_debt_goal_response(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
) -> GoalResponse:
    db.expire_all()
    goal = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
    )
    evaluation, _ = _evaluate_and_maybe_latch(db, goal, persist=False)
    return _debt_goal_response(goal, evaluation)


def _stage_debt_repayment_goal(
    db: Session,
    *,
    tenant_id: str,
    payload: GoalCreateRequest,
) -> Goal:
    """Validate and stage a debt goal plus its first frozen link batch."""
    if payload.month is not None or payload.category is not None or payload.target_amount_cents is not None:
        raise AppError(
            "invalid_request",
            "还债目标不接受月份 / 分类 / 目标金额。",
            status_code=422,
        )
    if not payload.debt_public_ids:
        _require_at_least_one_debt()
    debts = _resolve_linked_debts(
        db,
        tenant_id=tenant_id,
        debt_public_ids=payload.debt_public_ids,
    )
    now = now_utc()
    goal = Goal(
        tenant_id=tenant_id,
        name=_clean_name(payload.name),
        goal_type=GOAL_TYPE,
        period="monthly",
        month=None,
        category=None,
        target_amount_cents=None,
        status="active",
        goal_version=1,
        target_date=payload.target_date,
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.flush()
    for debt in debts:
        db.add(
            DebtGoalLink(
                goal_id=goal.id,
                goal_version=1,
                debt_id=debt.id,
                created_at=now,
            )
        )
    db.flush()
    return goal


def create_debt_repayment_goal(
    db: Session,
    *,
    tenant_id: str,
    payload: GoalCreateRequest,
) -> GoalResponse:
    """Create a debt-repayment goal at ``goal_version=1``."""
    goal = _stage_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        payload=payload,
    )
    evaluation, _ = _evaluate_and_maybe_latch(db, goal, persist=True)
    db.commit()
    db.expire_all()
    current = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=goal.public_id,
    )
    return _debt_goal_response(current, evaluation)


def _create_claim(
    db: Session,
    *,
    tenant_id: str,
    payload: GoalCreateRequest,
    idempotency_key: str | None,
) -> ApiIdempotencyKey | None:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=_CREATE_OPERATION,
        target_id=idempotency_key,
        body=payload.model_dump(mode="json", exclude_unset=True),
        expected_row_version=None,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        operation=_CREATE_OPERATION,
        request_fingerprint=fingerprint,
        target_type=_GOAL_TARGET_TYPE,
        target_id=idempotency_key,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:
        return None
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    return outcome.row


def _created_goal_public_id_for_key(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str,
) -> str:
    row = db.scalar(
        select(ApiIdempotencyKey)
        .where(ApiIdempotencyKey.tenant_id == tenant_id)
        .where(ApiIdempotencyKey.idempotency_key == idempotency_key)
        .limit(1)
    )
    if row is None or row.status != "succeeded" or not row.resource_id:
        raise AppError("idempotency_key_in_progress", status_code=409)
    return row.resource_id


def create_debt_repayment_goal_idempotently(
    db: Session,
    *,
    tenant_id: str,
    payload: GoalCreateRequest,
    idempotency_key: str | None,
) -> GoalResponse:
    """Create the business rows and idempotency success in one transaction."""
    claim = _create_claim(
        db,
        tenant_id=tenant_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    assert idempotency_key
    if claim is None:
        return _canonical_debt_goal_response(
            db,
            tenant_id=tenant_id,
            public_id=_created_goal_public_id_for_key(
                db,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
            ),
        )
    goal = _stage_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        payload=payload,
    )
    evaluation, _ = _evaluate_and_maybe_latch(db, goal, persist=True)
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_GOAL_TARGET_TYPE,
        resource_id=goal.public_id,
    )
    db.commit()
    db.expire_all()
    current = _require_debt_repayment_goal(
        db,
        tenant_id=tenant_id,
        public_id=goal.public_id,
    )
    return _debt_goal_response(current, evaluation)


def list_debt_repayment_goals(
    db: Session,
    *,
    tenant_id: str,
    include_archived: bool = False,
    persist_achievement: bool = False,
) -> list[GoalResponse]:
    """List one ledger's debt-repayment goals."""
    statement = ledger_scoped_select(Goal, tenant_id).where(Goal.goal_type == GOAL_TYPE)
    if not include_archived:
        statement = statement.where(Goal.status != "archived")
    statement = statement.order_by(
        Goal.status.asc(),
        Goal.created_at.asc(),
        Goal.id.asc(),
    )
    goals = list(db.scalars(statement))
    return [
        build_debt_repayment_goal_response(
            db,
            goal,
            persist_achievement=persist_achievement,
        )
        for goal in goals
    ]


def ledger_has_goal_needing_review(db: Session, *, tenant_id: str) -> bool:
    """Return whether any active debt goal has unresolved link integrity."""
    return any(
        goal.debt_repayment is not None and goal.debt_repayment.needs_review
        for goal in list_debt_repayment_goals(db, tenant_id=tenant_id)
    )
