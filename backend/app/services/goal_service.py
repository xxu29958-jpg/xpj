from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Goal
from app.schemas import GoalCreateRequest, GoalResponse, GoalUpdateRequest
from app.services.category_service import normalize_category
from app.services.optimistic_concurrency import bump_row_version, claim_row_with_token
from app.services.spending_contract_service import clean_month, confirmed_amount_query
from app.services.time_service import now_utc

VALID_GOAL_TYPES = {"spending_limit"}
VALID_PERIODS = {"monthly"}


class GoalSpendTotals:
    def __init__(self, total_amount_cents: int, by_category: dict[str, int]) -> None:
        self.total_amount_cents = total_amount_cents
        self.by_category = by_category


def _clean_month(month: str) -> str:
    return clean_month(month)


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 80:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _clean_goal_type(goal_type: str | None) -> str:
    cleaned = (goal_type or "spending_limit").strip()
    if cleaned not in VALID_GOAL_TYPES:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _clean_period(period: str | None) -> str:
    cleaned = (period or "monthly").strip()
    if cleaned not in VALID_PERIODS:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _clean_category(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if len(raw) > 64:
        raise AppError("invalid_request", status_code=422)
    return normalize_category(raw)


def _clean_target_amount(value: int) -> int:
    amount = int(value)
    if amount <= 0:
        raise AppError("invalid_request", status_code=422)
    return amount


def _month_spend_totals(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None = None,
) -> GoalSpendTotals:
    filtered = confirmed_amount_query(
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    ).subquery()
    rows = db.execute(
        select(
            filtered.c.category,
            func.coalesce(func.sum(filtered.c.amount_cents), 0),
        )
        .select_from(filtered)
        .group_by(filtered.c.category)
    )
    total_amount_cents = 0
    by_category: dict[str, int] = {}
    for category_raw, amount_value in rows:
        amount = int(amount_value or 0)
        total_amount_cents += amount
        category = normalize_category(category_raw)
        by_category[category] = by_category.get(category, 0) + amount
    return GoalSpendTotals(total_amount_cents, by_category)


def _progress_state(goal: Goal, spent_amount_cents: int) -> str:
    if goal.status == "archived":
        return "archived"
    if spent_amount_cents <= 0:
        return "not_started"
    if spent_amount_cents >= goal.target_amount_cents:
        return "over_limit"
    if spent_amount_cents * 100 >= goal.target_amount_cents * 80:
        return "near_limit"
    return "on_track"


def goal_response(goal: Goal, totals: GoalSpendTotals) -> GoalResponse:
    spent = totals.by_category.get(goal.category, 0) if goal.category else totals.total_amount_cents
    target = int(goal.target_amount_cents)
    return GoalResponse(
        public_id=goal.public_id,
        ledger_id=goal.tenant_id,
        name=goal.name,
        goal_type=goal.goal_type,
        period=goal.period,
        month=goal.month,
        category=goal.category,
        target_amount_cents=target,
        spent_amount_cents=spent,
        remaining_amount_cents=target - spent,
        progress_percent=(spent * 100) // target,
        progress_state=_progress_state(goal, spent),
        status=goal.status,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        row_version=goal.row_version,
        archived_at=goal.archived_at,
    )


def _goal_by_public_id(db: Session, *, tenant_id: str, public_id: str) -> Goal | None:
    return db.scalar(
        ledger_scoped_select(Goal, tenant_id)
        .where(Goal.public_id == public_id)
        .limit(1)
    )


def get_goal(db: Session, *, tenant_id: str, public_id: str) -> Goal:
    goal = _goal_by_public_id(db, tenant_id=tenant_id, public_id=public_id)
    if goal is None:
        raise AppError("goal_not_found", status_code=404)
    return goal


def _raise_duplicate_goal() -> None:
    raise AppError(
        "invalid_request",
        "同一账本、月份和分类只能有一个启用中的目标。",
        status_code=409,
    )


def _active_goal_conflict_exists(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    category: str | None,
    goal_type: str,
    period: str,
    exclude_public_id: str | None = None,
) -> bool:
    statement = (
        ledger_scoped_select(Goal, tenant_id)
        .where(Goal.status == "active")
        .where(Goal.month == month)
        .where(Goal.goal_type == goal_type)
        .where(Goal.period == period)
    )
    if category is None:
        statement = statement.where(Goal.category.is_(None))
    else:
        statement = statement.where(Goal.category == category)
    if exclude_public_id is not None:
        statement = statement.where(Goal.public_id != exclude_public_id)
    return db.scalar(statement.limit(1)) is not None


def list_goals(
    db: Session,
    *,
    tenant_id: str,
    month: str,
    timezone_name: str | None = None,
    include_archived: bool = False,
) -> list[GoalResponse]:
    month = _clean_month(month)
    statement = ledger_scoped_select(Goal, tenant_id).where(Goal.month == month)
    if not include_archived:
        statement = statement.where(Goal.status != "archived")
    # nulls_first(): the total goal (category IS NULL) must sort before the
    # per-category goals. PostgreSQL sorts NULLs last by default, SQLite first,
    # so an unqualified ``category.asc()`` flips the order across dialects
    # (ADR-0041). SQLite 3.30+ understands NULLS FIRST.
    statement = statement.order_by(
        Goal.status.asc(),
        Goal.category.asc().nulls_first(),
        Goal.created_at.asc(),
        Goal.id.asc(),
    )
    goals = list(db.scalars(statement))
    totals = _month_spend_totals(
        db,
        tenant_id=tenant_id,
        month=month,
        timezone_name=timezone_name,
    )
    return [goal_response(goal, totals) for goal in goals]


def get_goal_response(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    timezone_name: str | None = None,
) -> GoalResponse:
    goal = get_goal(db, tenant_id=tenant_id, public_id=public_id)
    totals = _month_spend_totals(
        db,
        tenant_id=tenant_id,
        month=goal.month,
        timezone_name=timezone_name,
    )
    return goal_response(goal, totals)


def create_goal(
    db: Session,
    *,
    tenant_id: str,
    payload: GoalCreateRequest,
    timezone_name: str | None = None,
) -> GoalResponse:
    now = now_utc()
    goal_type = _clean_goal_type(payload.goal_type)
    period = _clean_period(payload.period)
    month = _clean_month(payload.month)
    category = _clean_category(payload.category)
    if _active_goal_conflict_exists(
        db,
        tenant_id=tenant_id,
        month=month,
        category=category,
        goal_type=goal_type,
        period=period,
    ):
        _raise_duplicate_goal()
    goal = Goal(
        tenant_id=tenant_id,
        name=_clean_name(payload.name),
        goal_type=goal_type,
        period=period,
        month=month,
        category=category,
        target_amount_cents=_clean_target_amount(payload.target_amount_cents),
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _raise_duplicate_goal()
    db.refresh(goal)
    totals = _month_spend_totals(
        db,
        tenant_id=tenant_id,
        month=goal.month,
        timezone_name=timezone_name,
    )
    return goal_response(goal, totals)


def update_goal(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: GoalUpdateRequest,
    timezone_name: str | None = None,
    commit: bool = True,
) -> GoalResponse:
    """ADR-0038 PR-2j: atomic optimistic-concurrency PATCH.

    Validates the new fields then runs ``UPDATE goals SET ...,
    updated_at = now WHERE id, tenant_id, status='active', updated_at =
    expected``. ``rowcount == 0`` disambiguates: row vanished /
    no longer active → 404 ``goal_not_found``; else → 409
    ``state_conflict``. Archived check happens at the DB predicate
    layer so a peer archiving between the read and this PATCH
    surfaces as state_conflict, not a silent overwrite of an
    archived row.

    ADR-0042: ``commit=False`` lets the route commit the OCC claim together
    with the idempotency-key success record in a single transaction (§4.5);
    the row is still flushed + expired so the re-read sees the post-UPDATE
    state. The OCC-conflict path always rolls back its own placeholder
    regardless of ``commit``.
    """
    goal = get_goal(db, tenant_id=tenant_id, public_id=public_id)
    if goal.status == "archived":
        raise AppError("invalid_request", "目标已归档，不能继续修改。", status_code=409)

    updates = payload.model_dump(
        exclude_unset=True, exclude={"expected_row_version"}
    )
    goal_id = goal.id
    new_name = goal.name
    new_month = goal.month
    new_category = goal.category
    new_target = goal.target_amount_cents
    if "name" in updates:
        new_name = _clean_name(updates["name"])
    if "month" in updates:
        new_month = _clean_month(updates["month"])
    if "category" in updates:
        new_category = _clean_category(updates["category"])
    if "target_amount_cents" in updates:
        new_target = _clean_target_amount(updates["target_amount_cents"])
    if _active_goal_conflict_exists(
        db,
        tenant_id=tenant_id,
        month=new_month,
        category=new_category,
        goal_type=goal.goal_type,
        period=goal.period,
        exclude_public_id=goal.public_id,
    ):
        _raise_duplicate_goal()

    now = now_utc()
    try:
        rowcount = claim_row_with_token(
            db,
            Goal,
            pk_id=goal_id,
            tenant_id=tenant_id,
            expected_row_version=payload.expected_row_version,
            set_values={
                "name": new_name,
                "month": new_month,
                "category": new_category,
                "target_amount_cents": new_target,
                "updated_at": now,
            },
            extra_where=(Goal.status == "active",),
            synchronize_session=False,
        )
    except IntegrityError:
        db.rollback()
        _raise_duplicate_goal()
    if rowcount != 1:
        db.rollback()
        current = get_goal(db, tenant_id=tenant_id, public_id=public_id)
        if current.status != "active":
            raise AppError("invalid_request", "目标已归档，不能继续修改。", status_code=409)
        raise AppError("state_conflict", status_code=409)
    if commit:
        db.commit()
    else:
        db.flush()
    # synchronize_session=False left the identity-mapped row stale; drop it so
    # the re-read below reflects the UPDATE (whether committed or only flushed).
    db.expire_all()
    goal = get_goal(db, tenant_id=tenant_id, public_id=public_id)
    totals = _month_spend_totals(
        db,
        tenant_id=tenant_id,
        month=goal.month,
        timezone_name=timezone_name,
    )
    return goal_response(goal, totals)


def archive_goal(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    timezone_name: str | None = None,
) -> GoalResponse:
    goal = get_goal(db, tenant_id=tenant_id, public_id=public_id)
    if goal.status != "archived":
        now = now_utc()
        goal.status = "archived"
        goal.archived_at = now
        goal.updated_at = now
        bump_row_version(goal)
        db.commit()
        db.refresh(goal)
    totals = _month_spend_totals(
        db,
        tenant_id=tenant_id,
        month=goal.month,
        timezone_name=timezone_name,
    )
    return goal_response(goal, totals)
