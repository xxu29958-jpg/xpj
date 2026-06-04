from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    CategoryRuleCreateRequest,
    CategoryRuleDeleteRequest,
    CategoryRuleResponse,
    CategoryRuleUpdateRequest,
    RuleApplicationBatchResponse,
    RuleApplicationListResponse,
    RuleApplicationRollbackResponse,
    RuleApplyConfirmedRequest,
    RuleApplyConfirmedResponse,
    RuleApplyPendingPreviewItem,
    RuleApplyPendingPreviewResponse,
    RuleApplyPendingRequest,
    RuleApplyPendingResponse,
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
    get_rule_for_tenant,
    list_rule_applications,
    list_rules,
    preview_apply_rules_to_confirmed,
    preview_apply_rules_to_pending,
    preview_rule_for_pending,
    rollback_rule_application,
    undo_delete_rule,
    update_rule,
    validate_rule_application_preview,
)
from app.services.idempotency import (
    claim_idempotent_request,
    mark_idempotency_succeeded,
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> CategoryRuleResponse:
    # ADR-0038: client sends `expected_row_version`; update_rule raises
    # state_conflict 409 if the server's current value differs. ADR-0042: the
    # outbox-routed PATCH claims the Idempotency-Key before that OCC claim.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="update_category_rule",
        target_id=str(rule_id),
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="category_rule",
    )
    if claim is None:  # §4.6 HIT — re-serialise the current rule
        return get_rule_for_tenant(db, tenant_id=auth.tenant_id, rule_id=rule_id)

    rule = get_rule_for_tenant(db, tenant_id=auth.tenant_id, rule_id=rule_id)
    field_updates = payload.model_dump(
        exclude={"expected_row_version"}, exclude_unset=True
    )
    result = update_rule(
        db,
        rule,
        expected_row_version=payload.expected_row_version,
        commit=False,
        **field_updates,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="category_rule", resource_id=str(rule_id)
    )
    db.commit()
    return result


@router.delete("/categories/{rule_id}", response_model=StatusResponse)
def delete_category_rule(
    rule_id: int,
    payload: CategoryRuleDeleteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> StatusResponse:
    # ADR-0038: DELETE carries `expected_row_version` so stale clicks surface as
    # state_conflict 409. ADR-0042: claim the key before that OCC claim; a HIT
    # means the soft-delete already landed (idempotent — return ok).
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation="delete_category_rule",
        target_id=str(rule_id),
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
        target_type="category_rule",
    )
    if claim is None:  # §4.6 HIT — already deleted
        return StatusResponse()

    rule = get_rule_for_tenant(db, tenant_id=auth.tenant_id, rule_id=rule_id)
    delete_rule(
        db, rule, expected_row_version=payload.expected_row_version, commit=False
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="category_rule", resource_id=str(rule_id)
    )
    db.commit()
    return StatusResponse()


@router.post("/categories/{rule_id}/undo", response_model=CategoryRuleResponse)
def undo_category_rule(
    rule_id: int,
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> CategoryRuleResponse:
    # ADR-0038 undo: restore a soft-deleted rule within the retention window.
    # No `expected_row_version` — undo targets the soft-deleted row by id and is
    # a no-op-or-restore; once cleanup purges it (or if it was never
    # soft-deleted) this returns 404 rule_not_found.
    return undo_delete_rule(
        db,
        tenant_id=auth.tenant_id,
        rule_id=rule_id,
        actor_account_id=auth.account_id,
    )


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
    payload: RuleApplyPendingRequest | None = None,
    auth: AuthContext = Depends(get_current_writer_context),
    max_scan: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> RuleApplyPendingResponse:
    confirmed = bool(payload and payload.confirm)
    if not confirmed:
        raise AppError(
            "preview_required",
            "请先预览待确认账单影响范围，再确认应用。",
            status_code=409,
        )
    validate_rule_application_preview(
        db,
        tenant_id=auth.tenant_id,
        status="pending",
        preview_token=payload.preview_token if payload else None,
        max_scan=max_scan,
    )
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
        preview_token=result["preview_token"],
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
    current_preview = validate_rule_application_preview(
        db,
        tenant_id=auth.tenant_id,
        status="confirmed",
        preview_token=payload.preview_token,
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
