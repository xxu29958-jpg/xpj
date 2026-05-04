from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import verify_app_token
from app.database import get_db
from app.errors import AppError
from app.models import CategoryRule
from app.schemas import CategoryRuleCreateRequest, CategoryRuleResponse, CategoryRuleUpdateRequest, StatusResponse
from app.services.classify_service import create_rule, delete_rule, list_rules, update_rule


router = APIRouter(
    prefix="/api/rules",
    tags=["rules"],
    dependencies=[Depends(verify_app_token)],
)


@router.get("/categories", response_model=list[CategoryRuleResponse])
def get_category_rules(db: Session = Depends(get_db)) -> list[CategoryRuleResponse]:
    return list_rules(db)


@router.post("/categories", response_model=CategoryRuleResponse)
def post_category_rule(
    payload: CategoryRuleCreateRequest,
    db: Session = Depends(get_db),
) -> CategoryRuleResponse:
    return create_rule(
        db,
        keyword=payload.keyword,
        category=payload.category,
        enabled=payload.enabled,
        priority=payload.priority,
    )


@router.patch("/categories/{rule_id}", response_model=CategoryRuleResponse)
def patch_category_rule(
    rule_id: int,
    payload: CategoryRuleUpdateRequest,
    db: Session = Depends(get_db),
) -> CategoryRuleResponse:
    rule = db.get(CategoryRule, rule_id)
    if rule is None:
        raise AppError("rule_not_found", status_code=404)
    return update_rule(db, rule, **payload.model_dump(exclude_unset=True))


@router.delete("/categories/{rule_id}", response_model=StatusResponse)
def delete_category_rule(rule_id: int, db: Session = Depends(get_db)) -> StatusResponse:
    rule = db.get(CategoryRule, rule_id)
    if rule is None:
        raise AppError("rule_not_found", status_code=404)
    delete_rule(db, rule)
    return StatusResponse()
