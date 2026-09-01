"""Confirmed Expense correction commands and immutable history reads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
    ExpenseCorrectionRequest,
    ExpenseCorrectionResponse,
    ExpenseFactBundleResponse,
    ExpenseOffsetCorrectionRequest,
    ExpenseOffsetCreateRequest,
    ExpenseOffsetVoidRequest,
    ExpenseRevisionListResponse,
)
from app.services.expense_correction_service import (
    batch_update_confirmed_expenses,
    claim_correction_command,
    complete_correction_command,
    correction_idempotency_body,
)
from app.services.expense_offset_lifecycle_service import (
    correct_expense_offset,
    void_expense_offset,
)
from app.services.expense_offset_service import create_expense_offset, expense_fact_bundle
from app.services.expense_response_service import expense_to_response
from app.services.expense_revision_service import (
    list_expense_revisions,
    revision_by_idempotency_key,
    revision_to_response,
)
from app.services.expense_service import get_expense, resolve_expense, resolve_expense_for_mutation
from app.tenants import AuthContext

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


@router.post(
    "/confirmed/batch-update",
    response_model=ConfirmedExpenseBatchUpdateResponse,
)
def post_confirmed_expenses_batch_update(
    payload: ConfirmedExpenseBatchUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ConfirmedExpenseBatchUpdateResponse:
    return batch_update_confirmed_expenses(
        db,
        tenant_id=auth.tenant_id,
        payload=payload,
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{expense_id}/revisions",
    response_model=ExpenseRevisionListResponse,
)
def get_expense_revision_history(
    expense_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    snapshot_revision: int | None = Query(default=None, ge=0),
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> ExpenseRevisionListResponse:
    expense = get_expense(db, expense_id, auth.tenant_id)
    return list_expense_revisions(
        db,
        tenant_id=auth.tenant_id,
        expense_id=expense_id,
        current_revision=expense.fact_revision,
        snapshot_revision=snapshot_revision,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{expense_id}/corrections",
    response_model=ExpenseCorrectionResponse,
    status_code=201,
)
def post_expense_correction(
    expense_id: str,
    payload: ExpenseCorrectionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> ExpenseCorrectionResponse:
    expense_pk, effective_row_version = resolve_expense_for_mutation(
        db,
        auth.tenant_id,
        expense_id,
        device_id=auth.device_id,
        expected_row_version=payload.expected_row_version,
    )
    claim = claim_correction_command(
        db,
        expense_id=expense_pk,
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        intent_body=correction_idempotency_body(
            payload,
            actor_account_id=auth.account_id,
        ),
    )
    if claim is None:
        if idempotency_key is None:  # narrowed by claim_idempotent_request
            raise AppError("server_error", status_code=500)
        expense = get_expense(db, expense_pk, auth.tenant_id)
        revision = revision_by_idempotency_key(
            db,
            tenant_id=auth.tenant_id,
            idempotency_key=idempotency_key,
        )
        if revision is None:
            raise AppError("server_error", status_code=500)
        return ExpenseCorrectionResponse(
            expense=expense_to_response(
                db,
                tenant_id=auth.tenant_id,
                expense=expense,
            ),
            revision=revision_to_response(db, revision),
        )

    if idempotency_key is None:  # narrowed by claim_idempotent_request
        raise AppError("server_error", status_code=500)
    expense, revision = complete_correction_command(
        db,
        claim=claim,
        expense_id=expense_pk,
        tenant_id=auth.tenant_id,
        payload=payload.model_copy(update={"expected_row_version": effective_row_version}),
        actor_account_id=auth.account_id,
        actor_device_id=auth.device_id,
        idempotency_key=idempotency_key,
    )
    return ExpenseCorrectionResponse(
        expense=expense_to_response(
            db,
            tenant_id=auth.tenant_id,
            expense=expense,
        ),
        revision=revision_to_response(db, revision),
    )


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


@router.post(
    "/{expense_id}/offsets/{offset_public_id}/corrections",
    response_model=ExpenseFactBundleResponse,
    status_code=201,
)
def post_expense_offset_correction(
    expense_id: str,
    offset_public_id: str,
    payload: ExpenseOffsetCorrectionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
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
    return correct_expense_offset(
        db,
        tenant_id=auth.tenant_id,
        expense_id=expense.id,
        offset_public_id=offset_public_id,
        payload=payload,
        actor_account_id=auth.account_id,
        actor_device_public_id=auth.device_public_id,
        actor_device_name=auth.device_name,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{expense_id}/offsets/{offset_public_id}/voids",
    response_model=ExpenseFactBundleResponse,
    status_code=201,
)
def post_expense_offset_void(
    expense_id: str,
    offset_public_id: str,
    payload: ExpenseOffsetVoidRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
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
    return void_expense_offset(
        db,
        tenant_id=auth.tenant_id,
        expense_id=expense.id,
        offset_public_id=offset_public_id,
        payload=payload,
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
