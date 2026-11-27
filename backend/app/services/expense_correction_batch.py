"""Batch correction command for already-confirmed Expense facts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense
from app.schemas import (
    ConfirmedExpenseBatchUpdateRequest,
    ConfirmedExpenseBatchUpdateResponse,
)
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_revision_service import (
    prepare_correction_revision,
    record_prepared_correction_revision,
)
from app.services.expense_service._helpers import _clean_category
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.tag_service import normalize_tags, sync_expense_tags
from app.services.time_service import now_utc


@dataclass(frozen=True)
class _BatchCorrectionIntent:
    expense_ids: list[int]
    expected_by_id: dict[int, int]
    category_provided: bool
    category: str | None
    tags_provided: bool
    tags: list[str] | None


def _batch_correction_intent(
    payload: ConfirmedExpenseBatchUpdateRequest,
) -> _BatchCorrectionIntent:
    expense_ids = list(dict.fromkeys(payload.expense_ids))
    expected_by_id = payload.expected_row_version_by_id
    if set(expected_by_id) != set(expense_ids):
        raise AppError("invalid_request", status_code=422)

    category_provided = payload.category is not None
    tags_provided = payload.tags is not None
    if not category_provided and not tags_provided:
        raise AppError("invalid_request", status_code=422)
    category = payload.category.strip() if category_provided else None
    if category_provided and not category:
        raise AppError("invalid_request", status_code=422)
    return _BatchCorrectionIntent(
        expense_ids=expense_ids,
        expected_by_id=expected_by_id,
        category_provided=category_provided,
        category=category,
        tags_provided=tags_provided,
        tags=normalize_tags(payload.tags) if tags_provided else None,
    )


def _apply_one_batch_correction(
    db: Session,
    *,
    expense: Expense,
    tenant_id: str,
    expected_row_version: int,
    intent: _BatchCorrectionIntent,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
) -> bool:
    target_category = _clean_category(intent.category) if intent.category_provided else expense.category
    target_tags = intent.tags if intent.tags_provided else expense.tags
    if target_category == expense.category and target_tags == expense.tags:
        matched_id = db.scalar(
            select(Expense.id)
            .where(Expense.id == expense.id)
            .where(Expense.tenant_id == tenant_id)
            .where(Expense.status == "confirmed")
            .where(Expense.row_version == expected_row_version)
            .with_for_update(read=True)
        )
        if matched_id is None:
            db.rollback()
            raise AppError("state_conflict", status_code=409)
        return False

    prepared = prepare_correction_revision(db, expense)
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Expense,
        pk_id=expense.id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"updated_at": now, "fact_revision": Expense.fact_revision + 1},
        extra_where=(Expense.status == "confirmed",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        raise AppError("state_conflict", status_code=409)
    if intent.category_provided:
        expense.category = target_category
        ensure_category_preference_for_name(db, tenant_id=tenant_id, name=target_category)
    if intent.tags_provided:
        expense.tags = intent.tags
        sync_expense_tags(db, expense)
    expense.updated_at = now
    db.flush()
    db.refresh(expense)
    record_prepared_correction_revision(
        db,
        expense,
        prepared,
        reason=reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
    )
    return True


def _claim_batch_idempotency(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
    actor_account_id: int | None,
    idempotency_key: str | None,
) -> tuple[ApiIdempotencyKey | None, ConfirmedExpenseBatchUpdateResponse | None]:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="correct_confirmed_expense_batch",
        target_id="confirmed",
        target_type="expense_batch",
        body={
            **payload.model_dump(mode="json"),
            "actor_account_id": actor_account_id,
        },
        expected_row_version=None,
    )
    if claim is not None:
        return claim, None
    if idempotency_key is None:  # narrowed by claim_idempotent_request
        raise AppError("server_error", status_code=500)
    stored = db.scalar(
        select(ApiIdempotencyKey)
        .where(ApiIdempotencyKey.tenant_id == tenant_id)
        .where(ApiIdempotencyKey.idempotency_key == idempotency_key)
    )
    if stored is None or stored.response_body is None:
        raise AppError("server_error", status_code=500)
    return None, ConfirmedExpenseBatchUpdateResponse.model_validate(stored.response_body)


def batch_update_confirmed_expenses(
    db: Session,
    *,
    tenant_id: str,
    payload: ConfirmedExpenseBatchUpdateRequest,
    actor_account_id: int | None = None,
    actor_device_id: int | None = None,
    idempotency_key: str | None = None,
) -> ConfirmedExpenseBatchUpdateResponse:
    """Apply one reasoned correction intent to each eligible confirmed fact."""

    intent = _batch_correction_intent(payload)
    claim, replay = _claim_batch_idempotency(
        db,
        tenant_id=tenant_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
    )
    if replay is not None:
        return replay
    if claim is None:
        raise AssertionError("new batch command must hold an idempotency claim")

    authorize_currency_metadata_write(db)
    rows = list(
        db.scalars(select(Expense).where(Expense.tenant_id == tenant_id).where(Expense.id.in_(intent.expense_ids)))
    )
    rows_by_id = {row.id: row for row in rows}

    updated_count = 0
    skipped_not_found = 0
    skipped_not_confirmed = 0
    # Web and Android submit different selection orders; all row locks must
    # still be acquired in one global order for overlapping batches.
    for expense_id in sorted(intent.expense_ids):
        expense = rows_by_id.get(expense_id)
        if expense is None:
            skipped_not_found += 1
            continue
        if expense.status != "confirmed":
            skipped_not_confirmed += 1
            continue
        updated_count += int(
            _apply_one_batch_correction(
                db,
                expense=expense,
                tenant_id=tenant_id,
                expected_row_version=intent.expected_by_id[expense_id],
                intent=intent,
                reason=payload.reason,
                actor_account_id=actor_account_id,
                actor_device_id=actor_device_id,
            )
        )

    result = ConfirmedExpenseBatchUpdateResponse(
        requested_count=len(intent.expense_ids),
        updated_count=updated_count,
        skipped_not_found=skipped_not_found,
        skipped_not_confirmed=skipped_not_confirmed,
    )
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="expense_batch",
        resource_id="confirmed",
        response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result
