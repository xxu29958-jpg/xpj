"""Expense refund, chargeback, reversal commands and bundle reads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import ExpenseFactBundleResponse, ExpenseOffsetCreateRequest
from app.services.expense_offset_service import (
    create_expense_offset,
    expense_fact_bundle,
)
from app.services.expense_service import resolve_expense, resolve_expense_for_mutation
from app.tenants import AuthContext

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


@router.post(
    "/{expense_id}/offsets",
    response_model=ExpenseFactBundleResponse,
    status_code=201,
)
def post_expense_offset(
    expense_id: str,
    payload: ExpenseOffsetCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseFactBundleResponse:
    expense_pk, effective_row_version = resolve_expense_for_mutation(
        db,
        auth.tenant_id,
        expense_id,
        device_id=auth.device_id,
        expected_row_version=payload.expected_row_version,
    )
    return create_expense_offset(
        db,
        tenant_id=auth.tenant_id,
        expense_id=expense_pk,
        payload=payload,
        effective_expected_row_version=effective_row_version,
        actor_account_id=auth.account_id,
        actor_device_public_id=auth.device_public_id,
        actor_device_name=auth.device_name,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{expense_id}/fact-bundle",
    response_model=ExpenseFactBundleResponse,
)
def get_expense_fact_bundle(
    expense_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExpenseFactBundleResponse:
    expense = resolve_expense(
        db,
        auth.tenant_id,
        expense_id,
        device_id=auth.device_id,
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    return expense_fact_bundle(
        db,
        tenant_id=auth.tenant_id,
        expense_id=expense.id,
    )
