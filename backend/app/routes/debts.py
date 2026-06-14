"""ADR-0049 Debt domain routes (slice 1: list / get / create; slice 2: facts).

Thin route layer (§1): parse + auth + delegate to ``debt_service`` + return a
schema. No business logic, no SQL, no raw-exception leakage.

- ``GET /api/debts`` — ledger-scoped list with derived ``remaining`` / ``paid``.
- ``GET /api/debts/{public_id}`` — one Debt; 404 ``debt_not_found``.
- ``POST /api/debts`` — create one external/manual Debt.
- ``POST /api/debts/{public_id}/repayments`` — record a committed repayment (§3.1).
- ``POST /api/debts/{public_id}/adjustments`` — record a signed adjustment (§3.3).
- ``POST /api/debts/{public_id}/repayment-voids`` — void one repayment (§3.4).
- ``POST /api/debts/{public_id}/void`` — void the whole Debt (§3.5).

All writes are writers-only (``get_current_writer_context`` → viewer 403,
§5/§11), carry an ``Idempotency-Key`` ([[0042]]), and take ``expected_row_version``
in the body (§3.6 fingerprint + §2.1 stale-intent fence). Each replies with the
fold-after ``DebtResponse`` so the client has the fresh ``row_version``.

Create uses the low-level [[0042]] helpers directly (no path id to re-serialise
from on a HIT — the recorded ``resource_id`` locates the Debt). The fact writes
have a path id (the Debt ``public_id``) so they use the high-level
``claim_idempotent_request`` handshake: a HIT re-serialises the Debt's canonical
current fold WITHOUT re-entering the §2.1 serialized section (no second parent
bump, no second fact insert — §2.1 "replay does not bump").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.errors import AppError
from app.schemas import (
    DebtAdjustmentCreateRequest,
    DebtCreateRequest,
    DebtListResponse,
    DebtResponse,
    DebtVoidCreateRequest,
    RepaymentCreateRequest,
    RepaymentCreateResponse,
    RepaymentVoidCreateRequest,
)
from app.services.debt_service import (
    create_debt,
    get_debt_response,
    get_repayment_public_id_for_idempotency,
    list_debts,
    record_adjustment,
    record_repayment,
    void_debt,
    void_repayment,
)
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    claim_idempotent_request,
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
_REPAYMENT_OPERATION = "record_repayment"
_ADJUSTMENT_OPERATION = "record_adjustment"
_REPAYMENT_VOID_OPERATION = "void_repayment"
_DEBT_VOID_OPERATION = "void_debt"


def _repayment_create_response(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    repayment_public_id: str,
) -> RepaymentCreateResponse:
    debt = get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
    return RepaymentCreateResponse(
        **debt.model_dump(),
        repayment_public_id=repayment_public_id,
    )


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


@router.post(
    "/{public_id}/repayments",
    response_model=RepaymentCreateResponse,
    status_code=201,
)
def post_repayment(
    public_id: str,
    payload: RepaymentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> RepaymentCreateResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_REPAYMENT_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:  # §2.1 replay: re-serialise the fold, do NOT bump again.
        repayment_public_id = get_repayment_public_id_for_idempotency(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            idempotency_key=idempotency_key,
        )
        return _repayment_create_response(
            db,
            tenant_id=auth.tenant_id,
            public_id=public_id,
            repayment_public_id=repayment_public_id,
        )
    result = record_repayment(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type="repayment", resource_id=result.repayment_public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return _repayment_create_response(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        repayment_public_id=result.repayment_public_id,
    )


@router.post("/{public_id}/adjustments", response_model=DebtResponse, status_code=201)
def post_adjustment(
    public_id: str,
    payload: DebtAdjustmentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_ADJUSTMENT_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    debt = record_adjustment(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        actor_account_id=auth.account_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)


@router.post(
    "/{public_id}/repayment-voids", response_model=DebtResponse, status_code=201
)
def post_repayment_void(
    public_id: str,
    payload: RepaymentVoidCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    # The §2.1 serialization anchor is the parent Debt ``public_id``; the target
    # repayment id rides in the body + fingerprint.
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_REPAYMENT_VOID_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    debt = void_repayment(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        actor_account_id=auth.account_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)


@router.post("/{public_id}/void", response_model=DebtResponse, status_code=201)
def post_debt_void(
    public_id: str,
    payload: DebtVoidCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(get_current_writer_context),
    db: Session = Depends(get_db),
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=auth.tenant_id,
        operation=_DEBT_VOID_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
    debt = void_debt(
        db,
        tenant_id=auth.tenant_id,
        public_id=public_id,
        payload=payload,
        actor_account_id=auth.account_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db, claim, resource_type=_DEBT_TARGET_TYPE, resource_id=debt.public_id
    )
    db.commit()
    # bump_row_version emits a SQL ``row_version + 1`` expression; with
    # ``expire_on_commit=False`` the in-session Debt still holds that expression,
    # so expire before re-reading the fold for the response (mirrors
    # goal_service.update_goal's post-CAS expire_all).
    db.expire_all()
    return get_debt_response(db, tenant_id=auth.tenant_id, public_id=public_id)
