"""One monthly-budget save owns captured currency, OCC and the accepted receipt."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Budget, BudgetCategory
from app.schemas import BudgetMonthlyResponse, BudgetMonthlyUpdateRequest
from app.services.budget_money import validated_monthly_budget_amounts
from app.services.budget_service import (
    _budget_response,
    _clean_category_budget_rows,
    _clean_excluded_categories,
    _clean_month,
    _get_any_budget,
    _list_category_budgets,
    _serialize_excluded_categories,
)
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import normalize_currency_code
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc


def review_monthly_budget_save(db: Session, *, tenant_id: str, month: str, idempotency_key: str) -> bool:
    """Only a known accepted command permits a replacement key after user review."""
    row = db.scalar(select(ApiIdempotencyKey).where(
        ApiIdempotencyKey.tenant_id == tenant_id, ApiIdempotencyKey.idempotency_key == idempotency_key))
    if row is None:
        return False
    if (row.operation, row.target_type, row.target_id) != ("save_monthly_budget", "monthly_budget", month):
        raise AppError("idempotency_key_reused", status_code=422)
    if row.status != "succeeded":
        raise AppError("idempotency_key_in_progress", "原保存结果尚未确认，请保留输入并原样重试。", status_code=409)
    return True


def _claim_budget(db: Session, *, tenant_id: str, month: str, payload: BudgetMonthlyUpdateRequest, now: datetime) -> Budget:
    currency = normalize_currency_code(payload.home_currency_code)
    budget = _get_any_budget(db, tenant_id=tenant_id, month=month)
    if budget is None:
        if payload.expected_row_version is not None:
            raise AppError("state_conflict", "这月预算已发生变化，请保留输入并重新核对。", status_code=409)
        budget = db.scalar(insert(Budget).values(tenant_id=tenant_id, month=month, home_currency_code=currency,
            created_at=now, updated_at=now).on_conflict_do_nothing(constraint="uq_budgets_tenant_month").returning(Budget))
        if budget is None:
            raise AppError("state_conflict", "另一端已创建这月预算，请保留输入并重新核对。", status_code=409)
        return budget
    if budget.archived_at is not None:
        raise AppError("state_conflict", "这月预算已在回收站，请先恢复后再修改。", status_code=409)
    if payload.expected_row_version != budget.row_version:
        raise AppError("state_conflict", "另一端已修改预算，请保留输入并重新核对。", status_code=409)
    if budget.home_currency_code != currency:
        raise AppError("budget_currency_conflict", "输入币种与这月预算不同，请保留原金额并核对。", status_code=409)
    claimed = claim_row_with_token(db, Budget, pk_id=budget.id, tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version, set_values={"updated_at": now},
        extra_where=(Budget.archived_at.is_(None), Budget.home_currency_code == currency))
    if claimed != 1:
        raise AppError("state_conflict", "另一端已修改预算，请保留输入并重新核对。", status_code=409)
    return budget


def _save_categories(db: Session, *, tenant_id: str, month: str, categories: list[tuple[str, int]], now: datetime) -> None:
    existing = {row.category: row for row in _list_category_budgets(db, tenant_id=tenant_id, month=month)}
    for category, amount in categories:
        row = existing.pop(category, None)
        if row is None:
            row = BudgetCategory(tenant_id=tenant_id, month=month, category=category, created_at=now)
            db.add(row)
        row.amount_cents = amount
        row.updated_at = now
    for row in existing.values():
        db.delete(row)


def _apply_budget_save(db: Session, *, tenant_id: str, month: str,
    payload: BudgetMonthlyUpdateRequest, timezone_name: str | None) -> BudgetMonthlyResponse:
    amounts = validated_monthly_budget_amounts(payload)
    excluded = _clean_excluded_categories(payload.excluded_categories)
    categories = _clean_category_budget_rows(payload.category_budgets)
    resolve_write_capability(db)
    now = now_utc()
    budget = _claim_budget(db, tenant_id=tenant_id, month=month, payload=payload, now=now)
    budget.total_amount_cents, budget.non_monthly_amount_cents, budget.rollover_amount_cents = amounts
    budget.excluded_categories = _serialize_excluded_categories(excluded)
    budget.updated_at = now
    _save_categories(db, tenant_id=tenant_id, month=month, categories=categories, now=now)
    db.flush()
    return _budget_response(db, tenant_id=tenant_id, month=month, timezone_name=timezone_name)


def save_monthly_budget(db: Session, *, tenant_id: str, month: str,
    payload: BudgetMonthlyUpdateRequest, actor_account_id: int | None, idempotency_key: str | None,
    timezone_name: str | None = None) -> BudgetMonthlyResponse:
    month = _clean_month(month)
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    try:
        claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
            operation="save_monthly_budget", target_type="monthly_budget", target_id=month,
            request_fingerprint=fingerprint_request(operation="save_monthly_budget", target_id=month,
                body={"actor_account_id": actor_account_id, "intent": payload.model_dump(mode="json", exclude={"expected_row_version"})},
                expected_row_version=payload.expected_row_version))
        if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
            raise AppError("idempotency_key_in_progress", status_code=409)
        if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
            raise AppError("idempotency_key_reused", status_code=422)
        if claim.kind is IdempotencyOutcomeKind.HIT:
            return BudgetMonthlyResponse.model_validate(claim.row.response_body)
        response = _apply_budget_save(db, tenant_id=tenant_id, month=month, payload=payload, timezone_name=timezone_name)
        mark_idempotency_succeeded(db, claim.row, resource_type="monthly_budget", resource_id=month,
            response_body=response.model_dump(mode="json"))
        db.commit()
        return response
    except (AppError, SQLAlchemyError):
        db.rollback()
        raise
