"""Idempotent application commands shared by Debt API and HTML adapters.

Both JSON API and HTML Web adapters call these commands.  Keeping the
claim-before-OCC handshake here guarantees that a browser retry and an API
retry share the same actor-scoped fingerprint, atomic commit, and canonical
replay semantics instead of re-implementing the Debt contract per surface.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import (
    DebtAdjustmentCreateRequest,
    DebtCreateRequest,
    DebtForgiveCreateRequest,
    DebtKindSetRequest,
    DebtResponse,
    DebtVoidCreateRequest,
    RepaymentCreateRequest,
    RepaymentCreateResponse,
    RepaymentVoidCreateRequest,
)
from app.services.debt_service import (
    create_debt,
    forgive_debt,
    get_debt_response,
    get_participant_debt_response,
    get_repayment_public_id_for_idempotency,
    record_adjustment,
    record_repayment,
    set_debt_kind,
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

_DEBT_TARGET_TYPE = "debt"
_CREATE_OPERATION = "create_debt"
_REPAYMENT_OPERATION = "record_repayment"
_ADJUSTMENT_OPERATION = "record_adjustment"
_REPAYMENT_VOID_OPERATION = "void_repayment"
_DEBT_VOID_OPERATION = "void_debt"
_DEBT_FORGIVE_OPERATION = "forgive_debt"
_DEBT_KIND_OPERATION = "set_debt_kind"


def _actor_scoped_body(
    payload: RepaymentCreateRequest
    | DebtAdjustmentCreateRequest
    | DebtForgiveCreateRequest
    | DebtKindSetRequest
    | DebtVoidCreateRequest
    | RepaymentVoidCreateRequest,
    *,
    actor_account_id: int,
) -> dict[str, object]:
    body = payload.model_dump(
        mode="json",
        exclude_unset=True,
        exclude={"expected_row_version"},
    )
    return {**body, "actor_account_id": actor_account_id}


def create_debt_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    payload: DebtCreateRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    """Create one external/manual Debt with the collection-create replay contract."""
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    fingerprint = fingerprint_request(
        operation=_CREATE_OPERATION,
        target_id=idempotency_key,
        body={
            **payload.model_dump(mode="json", exclude_unset=True),
            "actor_account_id": actor_account_id,
        },
        expected_row_version=None,
    )
    outcome = claim_idempotency_key(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        operation=_CREATE_OPERATION,
        request_fingerprint=fingerprint,
        target_type=_DEBT_TARGET_TYPE,
        target_id=idempotency_key,
    )
    if outcome.kind is IdempotencyOutcomeKind.HIT:
        return get_debt_response(
            db,
            tenant_id=tenant_id,
            public_id=outcome.row.resource_id,
        )
    if outcome.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if outcome.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)

    debt = create_debt(
        db,
        tenant_id=tenant_id,
        created_by_account_id=actor_account_id,
        owner_account_id=actor_account_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        outcome.row,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=debt.public_id,
    )
    db.commit()
    db.expire_all()
    return get_debt_response(db, tenant_id=tenant_id, public_id=debt.public_id)


def _repayment_response(
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


def record_repayment_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: RepaymentCreateRequest,
    idempotency_key: str | None,
) -> RepaymentCreateResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_REPAYMENT_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_body(payload, actor_account_id=actor_account_id),
        expected_row_version=payload.expected_row_version,
    )
    assert idempotency_key
    if claim is None:
        repayment_public_id = get_repayment_public_id_for_idempotency(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            idempotency_key=idempotency_key,
        )
        return _repayment_response(
            db,
            tenant_id=tenant_id,
            public_id=public_id,
            repayment_public_id=repayment_public_id,
        )
    result = record_repayment(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        actor_account_id=actor_account_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="repayment",
        resource_id=result.repayment_public_id,
    )
    db.commit()
    db.expire_all()
    return _repayment_response(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        repayment_public_id=result.repayment_public_id,
    )


def record_adjustment_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: DebtAdjustmentCreateRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_ADJUSTMENT_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_body(payload, actor_account_id=actor_account_id),
        expected_row_version=payload.expected_row_version,
    )
    assert idempotency_key
    if claim is None:
        return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
    debt = record_adjustment(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        actor_account_id=actor_account_id,
        payload=payload,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=debt.public_id,
    )
    db.commit()
    db.expire_all()
    return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)


def void_repayment_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: RepaymentVoidCreateRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_REPAYMENT_VOID_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_body(payload, actor_account_id=actor_account_id),
        expected_row_version=payload.expected_row_version,
    )
    assert idempotency_key
    if claim is None:
        return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
    debt = void_repayment(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=debt.public_id,
    )
    db.commit()
    db.expire_all()
    return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)


def void_debt_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: DebtVoidCreateRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_DEBT_VOID_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_body(payload, actor_account_id=actor_account_id),
        expected_row_version=payload.expected_row_version,
    )
    assert idempotency_key
    if claim is None:
        return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
    debt = void_debt(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=debt.public_id,
    )
    db.commit()
    db.expire_all()
    return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)


def forgive_debt_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: DebtForgiveCreateRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_DEBT_FORGIVE_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_body(payload, actor_account_id=actor_account_id),
        expected_row_version=payload.expected_row_version,
    )
    assert idempotency_key
    if claim is None:
        return get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id=tenant_id,
            account_id=actor_account_id,
        )
    forgive_debt(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        actor_account_id=actor_account_id,
        expected_row_version=payload.expected_row_version,
        idempotency_key=idempotency_key,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=public_id,
    )
    db.commit()
    db.expire_all()
    return get_participant_debt_response(
        db,
        public_id=public_id,
        ledger_id=tenant_id,
        account_id=actor_account_id,
    )


def set_debt_kind_idempotently(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    payload: DebtKindSetRequest,
    idempotency_key: str | None,
) -> DebtResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation=_DEBT_KIND_OPERATION,
        target_id=public_id,
        target_type=_DEBT_TARGET_TYPE,
        body=_actor_scoped_body(payload, actor_account_id=actor_account_id),
        expected_row_version=payload.expected_row_version,
    )
    assert idempotency_key
    if claim is None:
        return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
    set_debt_kind(
        db,
        tenant_id=tenant_id,
        public_id=public_id,
        payload=payload,
        commit=False,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type=_DEBT_TARGET_TYPE,
        resource_id=public_id,
    )
    db.commit()
    db.expire_all()
    return get_debt_response(db, tenant_id=tenant_id, public_id=public_id)
