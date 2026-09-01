"""Correction and void commands for persisted Expense offset facts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, ExpenseOffsetFact, ExpenseOffsetRevision
from app.schemas import (
    ExpenseFactBundleResponse,
    ExpenseOffsetCorrectionRequest,
    ExpenseOffsetVoidRequest,
)
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_offset_money import resolve_corrected_offset_money
from app.services.expense_offset_service import (
    _offset_snapshot,
    _replayed_bundle,
    expense_fact_bundle,
)
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc


def _claim_correction(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    offset_public_id: str,
    payload: ExpenseOffsetCorrectionRequest,
    actor_account_id: int,
    idempotency_key: str | None,
) -> ApiIdempotencyKey | ExpenseFactBundleResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="correct_expense_offset",
        target_id=f"{expense_id}:{offset_public_id}",
        target_type="expense_offset",
        body={
            **payload.model_dump(mode="json", exclude={"expected_row_version"}),
            "actor_account_id": actor_account_id,
        },
        expected_row_version=payload.expected_row_version,
    )
    if claim is not None:
        return claim
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)
    return _replayed_bundle(db, tenant_id=tenant_id, idempotency_key=idempotency_key)


def _claim_void(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    offset_public_id: str,
    payload: ExpenseOffsetVoidRequest,
    actor_account_id: int,
    idempotency_key: str | None,
) -> ApiIdempotencyKey | ExpenseFactBundleResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="void_expense_offset",
        target_id=f"{expense_id}:{offset_public_id}",
        target_type="expense_offset",
        body={
            **payload.model_dump(mode="json", exclude={"expected_row_version"}),
            "actor_account_id": actor_account_id,
        },
        expected_row_version=payload.expected_row_version,
    )
    if claim is not None:
        return claim
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)
    return _replayed_bundle(db, tenant_id=tenant_id, idempotency_key=idempotency_key)


def _locked_lifecycle_rows(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    offset_public_id: str,
) -> tuple[Expense, ExpenseOffsetFact, list[ExpenseOffsetFact]]:
    expense = db.scalar(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.id == expense_id)
        .with_for_update()
    )
    if expense is None:
        raise AppError("expense_not_found", status_code=404)
    if expense.status != "confirmed" or expense.amount_cents is None:
        raise AppError("expense_not_confirmed", status_code=409)

    active_offsets = list(
        db.scalars(
            select(ExpenseOffsetFact)
            .where(ExpenseOffsetFact.tenant_id == tenant_id)
            .where(ExpenseOffsetFact.expense_id == expense_id)
            .where(ExpenseOffsetFact.status == "active")
            .order_by(ExpenseOffsetFact.id)
            .with_for_update()
        )
    )
    offset = next((item for item in active_offsets if item.public_id == offset_public_id), None)
    if offset is not None:
        return expense, offset, active_offsets

    existing = db.scalar(
        select(ExpenseOffsetFact)
        .where(ExpenseOffsetFact.tenant_id == tenant_id)
        .where(ExpenseOffsetFact.expense_id == expense_id)
        .where(ExpenseOffsetFact.public_id == offset_public_id)
        .with_for_update()
    )
    if existing is None:
        raise AppError("expense_offset_not_found", status_code=404)
    raise AppError("expense_offset_not_active", status_code=409)


def _bump_expense_root(
    db: Session,
    *,
    expense: Expense,
    now,
) -> None:
    claimed = claim_row_with_token(
        db,
        Expense,
        pk_id=expense.id,
        tenant_id=expense.tenant_id,
        expected_row_version=expense.row_version,
        set_values={"updated_at": now},
        extra_where=(Expense.status == "confirmed",),
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)


def _append_revision(
    db: Session,
    *,
    offset: ExpenseOffsetFact,
    before: dict[str, object],
    change_kind: str,
    reason: str,
    previous_version: int,
    actor_account_id: int,
    actor_device_public_id: str | None,
    actor_device_name: str | None,
    idempotency_key: str,
    created_at,
) -> None:
    db.add(
        ExpenseOffsetRevision(
            tenant_id=offset.tenant_id,
            expense_id=offset.expense_id,
            offset_id=offset.id,
            revision_number=offset.fact_revision,
            change_kind=change_kind,
            reason=reason,
            idempotency_key=idempotency_key,
            actor_account_id=actor_account_id,
            actor_device_public_id=actor_device_public_id,
            actor_device_name=actor_device_name,
            before_snapshot=before,
            after_snapshot=_offset_snapshot(offset),
            previous_row_version=previous_version,
            resulting_row_version=offset.row_version,
            created_at=created_at,
        )
    )
    db.flush()


def correct_expense_offset(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    offset_public_id: str,
    payload: ExpenseOffsetCorrectionRequest,
    actor_account_id: int,
    actor_device_public_id: str | None,
    actor_device_name: str | None,
    idempotency_key: str | None,
) -> ExpenseFactBundleResponse:
    claim_or_replay = _claim_correction(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        offset_public_id=offset_public_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
    )
    if isinstance(claim_or_replay, ExpenseFactBundleResponse):
        return claim_or_replay
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)

    authorize_currency_metadata_write(db)
    expense, offset, active_offsets = _locked_lifecycle_rows(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        offset_public_id=offset_public_id,
    )
    money = resolve_corrected_offset_money(
        db,
        tenant_id=tenant_id,
        expense=expense,
        offset=offset,
        active_offsets=active_offsets,
        payload=payload,
    )
    before = _offset_snapshot(offset)
    previous_version = offset.row_version
    now = now_utc()
    claimed_offset = claim_row_with_token(
        db,
        ExpenseOffsetFact,
        pk_id=offset.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={
            "original_amount_minor": money.original_amount_minor,
            "amount_cents": money.amount_cents,
            "exchange_rate_to_cny": money.exchange_rate_to_cny,
            "exchange_rate_date": money.exchange_rate_date,
            "exchange_rate_source": money.exchange_rate_source,
            "accounting_date": payload.accounting_date,
            "category": payload.category,
            "reason": payload.offset_reason,
            "fact_revision": ExpenseOffsetFact.fact_revision + 1,
            "updated_at": now,
        },
        extra_where=(ExpenseOffsetFact.status == "active",),
        synchronize_session=False,
    )
    if claimed_offset != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)
    _bump_expense_root(db, expense=expense, now=now)

    db.expire_all()
    corrected = db.scalar(
        select(ExpenseOffsetFact)
        .where(ExpenseOffsetFact.tenant_id == tenant_id)
        .where(ExpenseOffsetFact.id == offset.id)
    )
    if corrected is None:
        raise AppError("server_error", status_code=500)
    _append_revision(
        db,
        offset=corrected,
        before=before,
        change_kind="correction",
        reason=payload.correction_reason,
        previous_version=previous_version,
        actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id,
        actor_device_name=actor_device_name,
        idempotency_key=idempotency_key,
        created_at=now,
    )
    result = expense_fact_bundle(db, tenant_id=tenant_id, expense_id=expense_id)
    mark_idempotency_succeeded(
        db,
        claim_or_replay,
        resource_type="expense_offset",
        resource_id=corrected.public_id,
        response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result


def void_expense_offset(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    offset_public_id: str,
    payload: ExpenseOffsetVoidRequest,
    actor_account_id: int,
    actor_device_public_id: str | None,
    actor_device_name: str | None,
    idempotency_key: str | None,
) -> ExpenseFactBundleResponse:
    claim_or_replay = _claim_void(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        offset_public_id=offset_public_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
    )
    if isinstance(claim_or_replay, ExpenseFactBundleResponse):
        return claim_or_replay
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)

    authorize_currency_metadata_write(db)
    expense, offset, _ = _locked_lifecycle_rows(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        offset_public_id=offset_public_id,
    )
    before = _offset_snapshot(offset)
    previous_version = offset.row_version
    now = now_utc()
    claimed_offset = claim_row_with_token(
        db,
        ExpenseOffsetFact,
        pk_id=offset.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={
            "status": "voided",
            "voided_at": now,
            "updated_at": now,
            "fact_revision": ExpenseOffsetFact.fact_revision + 1,
        },
        extra_where=(ExpenseOffsetFact.status == "active",),
        synchronize_session=False,
    )
    if claimed_offset != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)
    _bump_expense_root(db, expense=expense, now=now)

    db.expire_all()
    voided = db.scalar(
        select(ExpenseOffsetFact)
        .where(ExpenseOffsetFact.tenant_id == tenant_id)
        .where(ExpenseOffsetFact.id == offset.id)
    )
    if voided is None:
        raise AppError("server_error", status_code=500)
    _append_revision(
        db,
        offset=voided,
        before=before,
        change_kind="void",
        reason=payload.void_reason,
        previous_version=previous_version,
        actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id,
        actor_device_name=actor_device_name,
        idempotency_key=idempotency_key,
        created_at=now,
    )
    result = expense_fact_bundle(db, tenant_id=tenant_id, expense_id=expense_id)
    mark_idempotency_succeeded(
        db,
        claim_or_replay,
        resource_type="expense_offset",
        resource_id=voided.public_id,
        response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result


__all__ = ["correct_expense_offset", "void_expense_offset"]
