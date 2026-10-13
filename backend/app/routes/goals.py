from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_protocol_writer_context, get_current_writer_context
from app.config import get_settings
from app.database import get_db
from app.schemas import (
    DebtGoalIntegrityReviewRequest,
    DebtGoalLinksReplaceRequest,
    DebtGoalTargetDateRequest,
    GoalCreateRequest,
    GoalHistoryResponse,
    GoalListResponse,
    GoalResponse,
    GoalTokenRequest,
    GoalUpdateRequest,
)
from app.services.goal_create_command import create_spending_goal_idempotently
from app.services.goal_debt_repayment_service import (
    acknowledge_integrity_review_idempotently,
    create_debt_repayment_goal_idempotently,
    list_debt_repayment_goals,
    replace_debt_repayment_goal_links_idempotently,
    set_debt_goal_target_date_idempotently,
)
from app.services.goal_history_service import goal_history
from app.services.goal_service import (
    archive_goal,
    create_goal,
    get_goal_response,
    list_goals,
    restore_goal,
)
from app.services.goal_update_command import update_goal_idempotently
from app.services.ledger_calendar_service import current_ledger_month
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/goals",
    tags=["goals"],
)


@router.get("", response_model=GoalListResponse)
def get_goals(
    month: str | None = None,
    include_archived: bool = False,
    goal_type: str | None = None,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> GoalListResponse:
    # ADR-0049 §6: ``goal_type=debt_repayment`` lists the (month-less) debt goals;
    # the default month-scoped path lists spending_limit goals only.
    if goal_type == "debt_repayment":
        return GoalListResponse(
            items=list_debt_repayment_goals(
                db,
                tenant_id=auth.tenant_id,
                include_archived=include_archived,
                persist_achievement=auth.role != "viewer",
            )
        )
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_ledger_month(db, ledger_id=auth.tenant_id)
    return GoalListResponse(
        items=list_goals(
            db,
            tenant_id=auth.tenant_id,
            month=target_month,
            timezone_name=timezone_name,
            include_archived=include_archived,
        )
    )


@router.get("/{public_id}", response_model=GoalResponse)
def get_goal_detail(
    public_id: str,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    # ADR-0049 §6: a writer's read of an all-cleared debt goal latches its
    # achievement (sticky); a viewer's read computes the state but never writes.
    return get_goal_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        timezone_name=timezone_name,
        persist_achievement=auth.role != "viewer",
    )


@router.post("", response_model=GoalResponse, status_code=201)
def post_goal(
    payload: GoalCreateRequest,
    timezone: str | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    if payload.goal_type.strip() == "debt_repayment":
        if idempotency_key is not None:
            return create_debt_repayment_goal_idempotently(
                db, tenant_id=auth.tenant_id, payload=payload, idempotency_key=idempotency_key,
            )
        return create_goal(db, tenant_id=auth.tenant_id, payload=payload, timezone_name=timezone_name)
    return create_spending_goal_idempotently(
        db,
        tenant_id=auth.tenant_id,
        payload=payload,
        timezone_name=timezone_name,
        idempotency_key=idempotency_key,
        actor_account_id=auth.account_id,
    )


@router.patch("/{public_id}", response_model=GoalResponse)
def patch_goal(
    public_id: str,
    payload: GoalUpdateRequest,
    timezone: str | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_protocol_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return update_goal_idempotently(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        timezone_name=timezone_name,
        idempotency_key=idempotency_key,
        actor_account_id=auth.account_id,
    )


@router.post("/{public_id}/archive", response_model=GoalResponse)
def post_goal_archive(
    public_id: str,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return archive_goal(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        timezone_name=timezone_name,
        actor_account_id=auth.account_id,
    )


@router.post("/{public_id}/restore", response_model=GoalResponse)
def post_goal_restore(
    public_id: str,
    payload: GoalTokenRequest,
    timezone: str | None = None,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    # ADR-0051 recycle-bin restore: OCC-gated reactivate (stale token → 409;
    # restoring into a peer-held active scope → duplicate 409). Archive stays
    # keyless. restore_goal dispatches the response by goal_type so a
    # debt_repayment goal (NULL target) doesn't crash int(None).
    timezone_name = timezone or get_settings().ocr_default_timezone
    return restore_goal(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        expected_row_version=payload.expected_row_version,
        timezone_name=timezone_name,
        actor_account_id=auth.account_id,
    )


@router.get("/{public_id}/history", response_model=GoalHistoryResponse)
def get_goal_history(
    public_id: str,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> GoalHistoryResponse:
    return goal_history(db, tenant_id=auth.tenant_id, public_id=public_id,
        before_version=before_version, limit=limit)


@router.post("/{public_id}/debt-links", response_model=GoalResponse)
def post_goal_debt_links(
    public_id: str,
    payload: DebtGoalLinksReplaceRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    return replace_debt_repayment_goal_links_idempotently(db, tenant_id=auth.tenant_id, public_id=public_id,
        payload=payload, idempotency_key=idempotency_key)


@router.post("/{public_id}/integrity-review/acknowledge", response_model=GoalResponse)
def post_goal_integrity_review_acknowledge(
    public_id: str,
    payload: DebtGoalIntegrityReviewRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    return acknowledge_integrity_review_idempotently(db, tenant_id=auth.tenant_id, public_id=public_id,
        payload=payload, idempotency_key=idempotency_key)


@router.post("/{public_id}/target-date", response_model=GoalResponse)
def post_goal_target_date(
    public_id: str,
    payload: DebtGoalTargetDateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    return set_debt_goal_target_date_idempotently(db, tenant_id=auth.tenant_id, public_id=public_id,
        payload=payload, idempotency_key=idempotency_key)
