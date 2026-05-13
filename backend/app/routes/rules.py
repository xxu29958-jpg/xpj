from __future__ import annotations

from fastapi import APIRouter, Depends
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
    RuleApplyPendingResponse,
    RulePreviewItem,
    RulePreviewRequest,
    RulePreviewResponse,
    StatusResponse,
)
from app.services.classify_service import (
    apply_rules_to_pending,
    create_rule,
    delete_rule,
    list_rules,
    preview_rule_for_pending,
    update_rule,
)
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
    db: Session = Depends(get_db),
) -> RuleApplyPendingResponse:
    pending_scanned, changed_count = apply_rules_to_pending(db, tenant_id=auth.tenant_id)
    return RuleApplyPendingResponse(
        pending_scanned=pending_scanned,
        changed_count=changed_count,
    )
