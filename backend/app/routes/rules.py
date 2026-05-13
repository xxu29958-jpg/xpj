from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CategoryRule
from app.schemas import (
    CategoryRuleCreateRequest,
    CategoryRuleResponse,
    CategoryRuleUpdateRequest,
    RuleApplyConfirmedRequest,
    RuleApplyConfirmedResponse,
    RuleApplyPendingResponse,
    RuleApplicationListResponse,
    RuleApplicationRollbackResponse,
    RuleApplyPendingPreviewItem,
    RuleApplyPendingPreviewResponse,
    RuleApplicationBatchResponse,
    RulePreviewItem,
    RulePreviewRequest,
    RulePreviewResponse,
    StatusResponse,
)
from app.services.classify_service import (
    apply_rules_to_confirmed,
    apply_rules_to_pending,
    create_rule,
    delete_rule,
    list_rule_applications,
    list_rules,
    preview_apply_rules_to_confirmed,
    preview_apply_rules_to_pending,
    preview_rule_for_pending,
    rollback_rule_application,
    update_rule,
)
from app.services.permission_service import require_write_expense
from app.tenants import AuthContext


router = APIRouter(
    prefix="/api/rules",
    tags=["rules"],
)


@router.get("/categories", response_model=list[CategoryRuleResponse])
def get_category_rules(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> list[CategoryRuleResponse]:
    return list_rules(db, auth.tenant_id)


@router.post("/categories", response_model=CategoryRuleResponse)
def post_category_rule(
    payload: CategoryRuleCreateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> CategoryRuleResponse:
    return create_rule(
        db,
        tenant_id=auth.tenant_id,
        keyword=payload.keyword,
        category=payload.category,
        enabled=payload.enabled,
        priority=payload.priority,
        amount_min_cents=payload.amount_min_cents,
        amount_max_cents=payload.amount_max_cents,
        source_contains=payload.source_contains,
        tag_contains=payload.tag_contains,
    )


@router.patch("/categories/{rule_id}", response_model=CategoryRuleResponse)
def patch_category_rule(
    rule_id: int,
    payload: CategoryRuleUpdateRequest,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> CategoryRuleResponse:
    rule = db.scalar(
        ledger_scoped_select(CategoryRule, auth.tenant_id).where(
            CategoryRule.id == rule_id
        )
    )
    if rule is None:
        raise AppError("rule_not_found", status_code=404)
    return update_rule(db, rule, **payload.model_dump(exclude_unset=True))


@router.delete("/categories/{rule_id}", response_model=StatusResponse)
def delete_category_rule(
    rule_id: int,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> StatusResponse:
    rule = db.scalar(
        ledger_scoped_select(CategoryRule, auth.tenant_id).where(
            CategoryRule.id == rule_id
        )
    )
    if rule is None:
        raise AppError("rule_not_found", status_code=404)
    delete_rule(db, rule)
    return StatusResponse()


# v0.4-alpha3 — Rules Preview & Apply --------------------------------


@router.post("/preview", response_model=RulePreviewResponse)
def post_rule_preview(
    payload: RulePreviewRequest,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RulePreviewResponse:
    matched_count, items = preview_rule_for_pending(
        db,
        tenant_id=auth.tenant_id,
        keyword=payload.keyword,
        target_category=payload.target_category,
        match_field=payload.match_field,
        limit=payload.limit,
    )
    return RulePreviewResponse(
        matched_count=matched_count,
        items=[RulePreviewItem(**item) for item in items],
    )


@router.post("/apply-pending", response_model=RuleApplyPendingResponse)
def post_rule_apply_pending(
    auth: AuthContext = Depends(get_current_writer_context),
    max_scan: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> RuleApplyPendingResponse:
    pending_scanned, changed_count, scan_limit_reached = apply_rules_to_pending(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
        max_scan=max_scan,
    )
    return RuleApplyPendingResponse(
        pending_scanned=pending_scanned,
        changed_count=changed_count,
        scan_limit_reached=scan_limit_reached,
        scan_limit=max_scan,
    )


@router.get("/applications", response_model=RuleApplicationListResponse)
def get_rule_applications(
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RuleApplicationListResponse:
    batches = list_rule_applications(db, tenant_id=auth.tenant_id, limit=limit)
    return RuleApplicationListResponse(
        items=[RuleApplicationBatchResponse.model_validate(batch) for batch in batches]
    )


@router.post(
    "/applications/{public_id}/rollback",
    response_model=RuleApplicationRollbackResponse,
)
def post_rule_application_rollback(
    public_id: str,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RuleApplicationRollbackResponse:
    batch, changed, skipped = rollback_rule_application(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
    )
    return RuleApplicationRollbackResponse(
        public_id=batch.public_id,
        status=batch.status,
        changed=changed,
        skipped=skipped,
        rolled_back_at=batch.rolled_back_at,
    )


@router.post("/apply-pending/preview", response_model=RuleApplyPendingPreviewResponse)
def post_rule_apply_pending_preview(
    limit: int = Query(default=20, ge=1, le=50),
    max_scan: int = Query(default=500, ge=1, le=1000),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RuleApplyPendingPreviewResponse:
    result = preview_apply_rules_to_pending(
        db,
        tenant_id=auth.tenant_id,
        limit=limit,
        max_scan=max_scan,
    )
    return RuleApplyPendingPreviewResponse(
        pending_scanned=result["pending_scanned"],
        changed_count=result["changed_count"],
        items=[RuleApplyPendingPreviewItem(**item) for item in result["items"]],
        skipped_non_default_category=result["skipped_non_default_category"],
        no_match_count=result["no_match_count"],
        unchanged_count=result["unchanged_count"],
        conflict_count=result["conflict_count"],
        scan_limit_reached=result["scan_limit_reached"],
        scan_limit=result["scan_limit"],
    )


@router.post("/apply-confirmed", response_model=RuleApplyConfirmedResponse)
def post_rule_apply_confirmed(
    payload: RuleApplyConfirmedRequest | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    max_scan: int = Query(default=500, ge=1, le=1000),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> RuleApplyConfirmedResponse:
    confirmed = bool(payload and payload.confirm)
    if not confirmed:
        result = preview_apply_rules_to_confirmed(
            db,
            tenant_id=auth.tenant_id,
            limit=limit,
            max_scan=max_scan,
        )
        return RuleApplyConfirmedResponse(
            dry_run=True,
            confirmed_scanned=result["confirmed_scanned"],
            changed_count=result["changed_count"],
            items=[RuleApplyPendingPreviewItem(**item) for item in result["items"]],
            skipped_non_default_category=result["skipped_non_default_category"],
            no_match_count=result["no_match_count"],
            unchanged_count=result["unchanged_count"],
            conflict_count=result["conflict_count"],
            scan_limit_reached=result["scan_limit_reached"],
            scan_limit=result["scan_limit"],
            preview_token=result["preview_token"],
        )

    require_write_expense(auth)
    if not payload.preview_token:
        raise AppError("preview_required", "请先预览历史账单影响范围，再确认应用。", status_code=409)
    current_preview = preview_apply_rules_to_confirmed(
        db,
        tenant_id=auth.tenant_id,
        limit=limit,
        max_scan=max_scan,
    )
    if current_preview["preview_token"] != payload.preview_token:
        raise AppError("preview_stale", "预览已过期，请重新预览后再确认。", status_code=409)
    confirmed_scanned, changed_count, scan_limit_reached = apply_rules_to_confirmed(
        db,
        tenant_id=auth.tenant_id,
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
        max_scan=max_scan,
    )
    return RuleApplyConfirmedResponse(
        dry_run=False,
        confirmed_scanned=confirmed_scanned,
        changed_count=changed_count,
        scan_limit_reached=scan_limit_reached,
        scan_limit=max_scan,
    )
