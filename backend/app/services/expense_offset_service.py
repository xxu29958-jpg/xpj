"""Single owner for Expense refund, chargeback, and reversal facts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    Account,
    ApiIdempotencyKey,
    Expense,
    ExpenseOffsetFact,
    ExpenseOffsetRevision,
)
from app.schemas import (
    ExpenseFactBundleResponse,
    ExpenseFinancialSummary,
    ExpenseOffsetCreateRequest,
    ExpenseOffsetResponse,
    ExpenseOffsetRevisionResponse,
)
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_response_service import expense_to_response
from app.services.expense_service import get_expense
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc, to_iso

__all__ = ["create_expense_offset", "expense_fact_bundle"]


def _require_confirmed(expense: Expense) -> None:
    if expense.status == "confirmed" and expense.amount_cents is not None:
        return
    if expense.status == "pending":
        raise AppError("expense_not_confirmed", status_code=409)
    raise AppError("expense_not_found", status_code=404)


def _gross_original_minor(expense: Expense) -> int:
    if expense.original_amount_minor is not None:
        return expense.original_amount_minor
    if expense.amount_cents is not None:
        return expense.amount_cents
    raise AppError("amount_required", status_code=409)


def _offset_snapshot(offset: ExpenseOffsetFact) -> dict[str, object]:
    return {
        "public_id": offset.public_id,
        "kind": offset.kind,
        "status": offset.status,
        "original_currency_code": offset.original_currency_code,
        "original_amount_minor": offset.original_amount_minor,
        "home_currency_code": offset.home_currency_code,
        "amount_cents": offset.amount_cents,
        "exchange_rate_to_cny": (
            format(offset.exchange_rate_to_cny, "f") if offset.exchange_rate_to_cny is not None else None
        ),
        "accounting_date": offset.accounting_date.isoformat(),
        "category": offset.category,
        "reason": offset.reason,
        "row_version": offset.row_version,
        "fact_revision": offset.fact_revision,
        "voided_at": to_iso(offset.voided_at),
    }


def _active_offsets(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    for_update: bool = False,
) -> list[ExpenseOffsetFact]:
    statement = (
        select(ExpenseOffsetFact)
        .where(ExpenseOffsetFact.tenant_id == tenant_id)
        .where(ExpenseOffsetFact.expense_id == expense_id)
        .where(ExpenseOffsetFact.status == "active")
        .order_by(ExpenseOffsetFact.accounting_date, ExpenseOffsetFact.id)
    )
    if for_update:
        statement = statement.with_for_update()
    return list(db.scalars(statement))


def _financial_summary(
    expense: Expense,
    offsets: list[ExpenseOffsetFact],
) -> ExpenseFinancialSummary:
    gross_original = _gross_original_minor(expense)
    gross_home = int(expense.amount_cents or 0)
    reversal = next((offset for offset in offsets if offset.kind == "reversal"), None)
    refunds = [offset for offset in offsets if offset.kind != "reversal"]
    refunded_original = sum(offset.original_amount_minor for offset in refunds)
    remaining_original = max(gross_original - refunded_original, 0)

    if reversal is not None:
        net_home = 0
        status = "reversed"
    else:
        net_home = gross_home - sum(offset.amount_cents for offset in refunds)
        if refunded_original == 0:
            status = "confirmed"
        elif remaining_original == 0:
            status = "fully_refunded"
        else:
            status = "partially_refunded"

    baseline_remaining_home = 0
    if gross_original:
        baseline_remaining_home = int(
            (Decimal(gross_home) * Decimal(remaining_original) / Decimal(gross_original)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return ExpenseFinancialSummary(
        gross_original_minor=gross_original,
        gross_home_amount_cents=gross_home,
        active_refunded_original_minor=refunded_original,
        remaining_refundable_original_minor=remaining_original,
        lineage_home_net_cents=net_home,
        fx_difference_cents=net_home - baseline_remaining_home,
        status=status,
    )


def _revision_to_response(
    db: Session,
    revision: ExpenseOffsetRevision,
    *,
    offset_public_id: str,
) -> ExpenseOffsetRevisionResponse:
    account_name = db.scalar(select(Account.display_name).where(Account.id == revision.actor_account_id))
    return ExpenseOffsetRevisionResponse(
        public_id=revision.public_id,
        offset_public_id=offset_public_id,
        revision_number=revision.revision_number,
        change_kind=revision.change_kind,
        reason=revision.reason,
        before=revision.before_snapshot,
        after=revision.after_snapshot,
        actor_account_name=account_name,
        actor_device_name=revision.actor_device_name,
        created_at=revision.created_at,
    )


def expense_fact_bundle(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
) -> ExpenseFactBundleResponse:
    expense = get_expense(db, expense_id, tenant_id)
    _require_confirmed(expense)
    offsets = _active_offsets(db, tenant_id=tenant_id, expense_id=expense_id)
    offset_by_id = {
        offset.id: offset.public_id
        for offset in db.scalars(
            select(ExpenseOffsetFact)
            .where(ExpenseOffsetFact.tenant_id == tenant_id)
            .where(ExpenseOffsetFact.expense_id == expense_id)
        )
    }
    revisions = list(
        db.scalars(
            select(ExpenseOffsetRevision)
            .where(ExpenseOffsetRevision.tenant_id == tenant_id)
            .where(ExpenseOffsetRevision.expense_id == expense_id)
            .order_by(ExpenseOffsetRevision.created_at.desc(), ExpenseOffsetRevision.id.desc())
            .limit(20)
        )
    )
    return ExpenseFactBundleResponse(
        root=expense_to_response(db, tenant_id=tenant_id, expense=expense),
        financial_summary=_financial_summary(expense, offsets),
        active_offsets=[ExpenseOffsetResponse.model_validate(offset) for offset in offsets],
        recent_history=[
            _revision_to_response(
                db,
                revision,
                offset_public_id=offset_by_id[revision.offset_id],
            )
            for revision in revisions
        ],
    )


def _replayed_bundle(
    db: Session,
    *,
    tenant_id: str,
    idempotency_key: str,
) -> ExpenseFactBundleResponse:
    record = db.scalar(
        select(ApiIdempotencyKey)
        .where(ApiIdempotencyKey.tenant_id == tenant_id)
        .where(ApiIdempotencyKey.idempotency_key == idempotency_key)
    )
    if record is None or record.response_body is None:
        raise AppError("server_error", status_code=500)
    return ExpenseFactBundleResponse.model_validate(record.response_body)


def create_expense_offset(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    payload: ExpenseOffsetCreateRequest,
    effective_expected_row_version: int,
    actor_account_id: int,
    actor_device_public_id: str | None,
    actor_device_name: str | None,
    idempotency_key: str | None,
) -> ExpenseFactBundleResponse:
    """Create one offset fact and publish its immutable first revision."""

    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="create_expense_offset",
        target_id=str(expense_id),
        target_type="expense_offset",
        body={
            **payload.model_dump(
                mode="json",
                exclude={"expected_row_version"},
            ),
            "actor_account_id": actor_account_id,
        },
        expected_row_version=payload.expected_row_version,
    )
    if claim is None:
        if idempotency_key is None:
            raise AppError("server_error", status_code=500)
        return _replayed_bundle(
            db,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)

    authorize_currency_metadata_write(db)
    current = get_expense(db, expense_id, tenant_id)
    _require_confirmed(current)
    now = now_utc()
    claimed = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=effective_expected_row_version,
        set_values={"updated_at": now},
        extra_where=(Expense.status == "confirmed",),
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        current = get_expense(db, expense_id, tenant_id)
        _require_confirmed(current)
        raise AppError("state_conflict", status_code=409)

    db.expire_all()
    expense = get_expense(db, expense_id, tenant_id)
    offsets = _active_offsets(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        for_update=True,
    )
    if any(offset.kind == "reversal" for offset in offsets):
        db.rollback()
        raise AppError("expense_reversal_active", status_code=409)

    gross_original = _gross_original_minor(expense)
    active_refunded = sum(offset.original_amount_minor for offset in offsets if offset.kind != "reversal")
    if payload.kind == "reversal":
        if active_refunded:
            db.rollback()
            raise AppError("expense_refund_exists", status_code=409)
        original_amount_minor = gross_original
        amount_cents = int(expense.amount_cents or 0)
    else:
        original_amount_minor = int(payload.original_amount_minor or 0)
        if original_amount_minor > gross_original - active_refunded:
            db.rollback()
            raise AppError("expense_refund_exceeds_remaining", status_code=409)
        if expense.original_currency_code != expense.home_currency_code:
            db.rollback()
            raise AppError("exchange_rate_required", status_code=409)
        amount_cents = original_amount_minor

    offset = ExpenseOffsetFact(
        tenant_id=tenant_id,
        expense_id=expense_id,
        kind=payload.kind,
        original_currency_code=expense.original_currency_code,
        original_amount_minor=original_amount_minor,
        home_currency_code=expense.home_currency_code,
        amount_cents=amount_cents,
        accounting_date=payload.accounting_date,
        category=expense.category,
        reason=payload.reason,
        created_actor_account_id=actor_account_id,
        created_device_public_id=actor_device_public_id,
        created_device_name=actor_device_name,
        created_at=now,
        updated_at=now,
    )
    db.add(offset)
    db.flush()
    db.refresh(offset)
    snapshot = _offset_snapshot(offset)
    revision = ExpenseOffsetRevision(
        tenant_id=tenant_id,
        expense_id=expense_id,
        offset_id=offset.id,
        revision_number=1,
        change_kind="created",
        reason=payload.reason,
        idempotency_key=idempotency_key,
        actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id,
        actor_device_name=actor_device_name,
        before_snapshot=None,
        after_snapshot=snapshot,
        previous_row_version=None,
        resulting_row_version=offset.row_version,
        created_at=now,
    )
    db.add(revision)
    db.flush()
    result = expense_fact_bundle(db, tenant_id=tenant_id, expense_id=expense_id)
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="expense_offset",
        resource_id=offset.public_id,
        response_body=result.model_dump(mode="json"),
    )
    db.commit()
    return result
