"""ADR-0049 Debt domain routes (slice 1: list / get / create).

Thin route layer (§1): parse + auth + delegate to ``debt_service`` + return a
schema. No business logic, no SQL, no raw-exception leakage.

- ``GET /api/debts`` — ledger-scoped list with derived ``remaining`` / ``paid``.
- ``GET /api/debts/{public_id}`` — one Debt; 404 ``debt_not_found``.
- ``POST /api/debts`` — create one external/manual Debt. Writers only
  (``get_current_writer_context`` → viewer 403, §5/§11). Carries an
  ``Idempotency-Key`` ([[0042]]); a replay returns the same Debt instead of
  creating a second one.

The create idempotency uses the low-level [[0042]] helpers directly (same
``api_idempotency_keys`` table, no second mechanism) because a create has no path
id to re-serialise from on a HIT — the recorded ``resource_id`` locates the Debt
the original request committed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import DebtCreateRequest, DebtListResponse, DebtResponse
from app.services.debt_service import create_debt, get_debt_response, list_debts
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.tenants import AuthContext

router = APIRouter(
    prefix="/api/debts",
    tags=["debts"],
)

_CREATE_OPERATION = "create_debt"
_DEBT_TARGET_TYPE = "debt"


@router.get("", response_model=DebtListResponse)
def get_debts(
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtListResponse:
    return list_debts(db, tenant_id=auth.tenant_id)


@router.get("/{public_id}", response_model=DebtResponse)
def get_debt_detail(
    public_id: str,
    auth: AuthContext = Depends(get_current_app_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)


@router.post("", response_model=DebtResponse, status_code=201)
def post_debt(
    payload: DebtCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    # ADR-0042: claim the Idempotency-Key BEFORE creating the row so an
    # offline-outbox replay of a committed-but-unseen create returns the SAME
    # Debt instead of inserting a second one. A create has no path id, so the
    # key itself anchors the fingerprint (per operation+key+body) and the
    # recorded ``resource_id`` locates the Debt on a HIT.
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=_CREATE_OPERATION,
        target_id=idempotency_key,
        body=payload.model_dump(mode="json", exclude_unset=True),
        expected_row_version=None,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=auth.tenant_id,
        idempotency_key=idempotency_key,
        operation=_CREATE_OPERATION,
        request_fingerprint=fingerprint,
        target_type=_DEBT_TARGET_TYPE,
        target_id=idempotency_key,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:  # §4.6 — re-serialise the created Debt
        return get_debt_response(
            db, tenant_id=auth.tenant_id, public_id=outcome.row.resource_id
        )
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)

    debt = create_debt(
        db,
        tenant_id=auth.tenant_id,
        created_by_account_id=auth.account_id,
        owner_account_id=auth.account_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, outcome.row, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=debt.public_id)
