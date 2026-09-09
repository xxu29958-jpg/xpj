"""Rule create/update command transactions shared by API and native Web forms."""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import CategoryRuleCreateRequest, CategoryRuleResponse, CategoryRuleUpdateRequest
from app.services.idempotency import (
    IdempotencyOutcome,
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.rule_service import create_rule, get_rule_for_tenant, update_rule


def _claim(db: Session, *, tenant_id: str, key: str | None, operation: str,
    rule_id: int | None, payload: CategoryRuleCreateRequest | CategoryRuleUpdateRequest) -> IdempotencyOutcome:
    if not key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(key) > 64:
        raise AppError("invalid_request", status_code=422)
    target = str(rule_id) if rule_id is not None else None
    updating = isinstance(payload, CategoryRuleUpdateRequest)
    claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=key, operation=operation,
        target_type="category_rule", target_id=target,
        request_fingerprint=fingerprint_request(operation=operation, target_id=target,
            body=payload.model_dump(mode="json", exclude_unset=updating, exclude={"expected_row_version"}),
            expected_row_version=payload.expected_row_version if updating else None))
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    return claim


def _accepted_receipt(claim: IdempotencyOutcome) -> CategoryRuleResponse:
    body = claim.row.response_body
    try:
        if not isinstance(body, dict) or "home_currency_code" not in body:
            raise ValueError("No captured receipt")
        receipt = CategoryRuleResponse.model_validate(body)
        if str(receipt.id) != claim.row.resource_id or (
            (receipt.amount_min_cents is not None or receipt.amount_max_cents is not None) and not receipt.home_currency_code
        ):
            raise ValueError("Incomplete original receipt")
        return receipt
    except (ValidationError, ValueError) as exc:
        raise AppError("rule_original_requires_review", "原提交已被接受，但缺少可核对的原回执。请核对规则后继续。", status_code=409) from exc


def create_rule_idempotently(db: Session, *, tenant_id: str, payload: CategoryRuleCreateRequest,
    idempotency_key: str | None) -> CategoryRuleResponse:
    claim = _claim(db, tenant_id=tenant_id, key=idempotency_key, operation="create_category_rule", rule_id=None, payload=payload)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _accepted_receipt(claim)
    rule = create_rule(db, tenant_id=tenant_id, commit=False, **payload.model_dump())
    result = CategoryRuleResponse.model_validate(rule)
    mark_idempotency_succeeded(db, claim.row, resource_type="category_rule", resource_id=str(result.id),
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result


def update_rule_idempotently(db: Session, *, tenant_id: str, rule_id: int,
    payload: CategoryRuleUpdateRequest, idempotency_key: str | None) -> CategoryRuleResponse:
    # Claim before OCC and the current row read: an unseen accepted update must
    # replay even after another writer changes or deletes its target.
    claim = _claim(db, tenant_id=tenant_id, key=idempotency_key, operation="update_category_rule", rule_id=rule_id, payload=payload)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _accepted_receipt(claim)
    rule = get_rule_for_tenant(db, tenant_id=tenant_id, rule_id=rule_id)
    result = CategoryRuleResponse.model_validate(update_rule(db, rule, commit=False,
        **payload.model_dump(exclude_unset=True)))
    mark_idempotency_succeeded(db, claim.row, resource_type="category_rule", resource_id=str(result.id),
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result
