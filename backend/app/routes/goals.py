from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.config import get_settings
from app.database import get_db
from app.schemas import (
    DebtGoalIntegrityReviewRequest,
    DebtGoalLinksReplaceRequest,
    DebtGoalTargetDateRequest,
    GoalCreateRequest,
    GoalListResponse,
    GoalResponse,
    GoalTokenRequest,
    GoalUpdateRequest,
)
from app.services.goal_debt_repayment_service import (
    acknowledge_integrity_review,
    list_debt_repayment_goals,
    replace_debt_repayment_goal_links,
    set_debt_goal_target_date,
)
from app.services.goal_service import (
    archive_goal,
    create_goal,
    get_goal_response,
    list_goals,
    restore_goal,
    update_goal,
)
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
)
from app.services.time_service import current_month
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
            )
        )
    timezone_name = timezone or get_settings().ocr_default_timezone
    target_month = month or current_month(timezone_name)
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
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    return create_goal(
        db,
        tenant_id=auth.tenant_id,
        payload=payload,
        timezone_name=timezone_name,
    )


@router.patch("/{public_id}", response_model=GoalResponse)
def patch_goal(
    public_id: str,
    payload: GoalUpdateRequest,
    timezone: str | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    timezone_name = timezone or get_settings().ocr_default_timezone
    # ADR-0038 PR-2j: ``expected_row_version`` token gates the PATCH (409 on a
    # stale snapshot). ADR-0042: claim the Idempotency-Key before that OCC claim
    # so an offline-outbox replay of a committed-but-unseen edit re-serialises
    # the goal instead of false-409ing on the bumped row_version.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="update_goal",
        target_id=public_id,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="goal",
    )
    if claim is None:  # §4.6 HIT — re-serialise the current goal
        return get_goal_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            timezone_name=timezone_name,
            persist_achievement=True,
        )

    result = update_goal(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        timezone_name=timezone_name,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="goal", resource_id=public_id
    )
    db.commit()
    return result


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
    )


@router.post("/{public_id}/debt-links", response_model=GoalResponse)
def post_goal_debt_links(
    public_id: str,
    payload: DebtGoalLinksReplaceRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    # ADR-0049 §6: replace a debt_repayment goal's linked Debt set → a new goal
    # version. Fold-changing OCC carrier (``expected_row_version`` bumps both the
    # goal's row_version and goal_version); idempotency follows the same shape as
    # PATCH (claim the key before the OCC claim, replay re-serialises the goal).
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="replace_debt_goal_links",
        target_id=public_id,
        body={"debt_public_ids": payload.debt_public_ids},
        expected_row_version=payload.expected_row_version,
        target_type="goal",
    )
    if claim is None:  # idempotent replay — re-serialise the current goal
        return get_goal_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            persist_achievement=True,
        )

    replace_debt_repayment_goal_links(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(db, claim, resource_type="goal", resource_id=public_id)
    db.commit()
    # The OCC claim used synchronize_session=False; drop the stale identity map so
    # the response re-reads the new goal_version + freshly written links.
    db.expire_all()
    return get_goal_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        persist_achievement=True,
    )


@router.post("/{public_id}/integrity-review/acknowledge", response_model=GoalResponse)
def post_goal_integrity_review_acknowledge(
    public_id: str,
    payload: DebtGoalIntegrityReviewRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    # ADR-0049 §6/F13: acknowledge ("keep for audit") an achieved debt_repayment
    # goal version whose linked set carries a debt-voided Debt — clears the integrity
    # needs_review for that version. OCC carrier + idempotency, same shape as the
    # link-replace route.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="acknowledge_debt_goal_integrity_review",
        target_id=public_id,
        body={},
        expected_row_version=payload.expected_row_version,
        target_type="goal",
    )
    if claim is None:  # idempotent replay — re-serialise the current goal
        return get_goal_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            persist_achievement=True,
        )

    acknowledge_integrity_review(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(db, claim, resource_type="goal", resource_id=public_id)
    db.commit()
    db.expire_all()
    return get_goal_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        persist_achievement=True,
    )


@router.post("/{public_id}/target-date", response_model=GoalResponse)
def post_goal_target_date(
    public_id: str,
    payload: DebtGoalTargetDateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> GoalResponse:
    # ADR-0049 §7.0 / 8e-6c: set or clear a debt_repayment goal's payoff deadline. OCC carrier
    # + idempotency, same shape as the link-replace / integrity-review routes; the claim bumps
    # ``row_version`` only (NOT ``goal_version``) so a deadline edit never un-achieves the goal.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="set_debt_goal_target_date",
        target_id=public_id,
        body={"target_date": payload.target_date.isoformat() if payload.target_date else None},
        expected_row_version=payload.expected_row_version,
        target_type="goal",
    )
    if claim is None:  # idempotent replay — re-serialise the current goal
        return get_goal_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            persist_achievement=True,
        )

    set_debt_goal_target_date(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(db, claim, resource_type="goal", resource_id=public_id)
    db.commit()
    db.expire_all()
    return get_goal_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        persist_achievement=True,
    )
