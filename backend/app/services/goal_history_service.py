"""Append spending definitions within the existing command transaction."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Goal, GoalRevision
from app.schemas._goal_history import GoalHistoryResponse, GoalRevisionResponse, GoalSnapshot
from app.services.time_service import now_utc


def lock_spending_goal(db: Session, goal: Goal) -> Goal:
    if goal.goal_type != "spending_limit":
        return goal
    locked = db.scalar(ledger_scoped_select(Goal, goal.tenant_id).where(Goal.id == goal.id)
        .with_for_update().execution_options(populate_existing=True))
    if locked is None:
        raise AppError("goal_not_found", status_code=404)
    return locked


def record_goal_revision(db: Session, goal: Goal, *, change_kind: str,
    actor_account_id: int | None = None) -> None:
    if goal.goal_type != "spending_limit":
        return
    snapshot = GoalSnapshot.model_validate({field: getattr(goal, field) for field in GoalSnapshot.model_fields})
    db.add(GoalRevision(tenant_id=goal.tenant_id, goal_id=goal.id, row_version=goal.row_version,
        change_kind=change_kind, snapshot=snapshot.model_dump(mode="json"),
        actor_account_id=actor_account_id, recorded_at=now_utc()))


def ensure_goal_history_baseline(db: Session, goal: Goal) -> None:
    # Call only after the original row is locked, before a real mutation.
    if goal.goal_type != "spending_limit":
        return
    recorded = db.scalar(select(GoalRevision.id).where(GoalRevision.tenant_id == goal.tenant_id,
        GoalRevision.goal_id == goal.id, GoalRevision.row_version == goal.row_version))
    if recorded is None:
        record_goal_revision(db, goal, change_kind="baseline")
        db.flush()


def goal_history(db: Session, *, tenant_id: str, public_id: str,
    before_version: int | None = None, limit: int = 20) -> GoalHistoryResponse:
    goal = db.scalar(ledger_scoped_select(Goal, tenant_id).where(
        Goal.public_id == public_id, Goal.goal_type == "spending_limit"))
    if goal is None:
        raise AppError("goal_not_found", status_code=404)
    query = select(GoalRevision).where(GoalRevision.tenant_id == tenant_id, GoalRevision.goal_id == goal.id)
    if before_version is not None:
        query = query.where(GoalRevision.row_version < before_version)
    rows = db.scalars(query.order_by(GoalRevision.row_version.desc()).limit(limit + 1)).all()
    selected = rows[:limit]
    return GoalHistoryResponse(ledger_id=tenant_id, public_id=public_id,
        items=[GoalRevisionResponse(row_version=row.row_version, change_kind=row.change_kind,
            recorded_at=row.recorded_at, snapshot=GoalSnapshot.model_validate(row.snapshot)) for row in selected],
        next_before_version=selected[-1].row_version if len(rows) > limit else None)
