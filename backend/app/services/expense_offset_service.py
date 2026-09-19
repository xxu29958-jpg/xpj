"""Single owner for Expense refund, chargeback, and reversal facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

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
    ExpenseOffsetCreateRequest,
    ExpenseOffsetResponse,
    ExpenseOffsetRevisionResponse,
)
from app.schemas._accounting_time import AccountingTimeSnapshot
from app.services.accounting_time_service import accounting_time_snapshot
from app.services.bill_split_service import (
    AcceptedSourceRelationship,
    settle_source_financial_change,
)
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.exchange_rate_service import ImportedCurrencyPayload
from app.services.expense_offset_money import (
    OffsetMoney,
    resolve_offset_money,
)
from app.services.expense_offset_relationship_projection import (
    relationship_impacts,
    source_relationship_reason,
)
from app.services.expense_offset_summary import expense_financial_summary
from app.services.expense_response_service import expense_to_response
from app.services.expense_service import get_expense
from app.services.idempotency import claim_idempotent_request, mark_idempotency_succeeded
from app.services.ledger_calendar_service import calendar_revision, current_calendar
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc, to_iso

__all__ = ["create_expense_offset", "expense_fact_bundle"]


@dataclass(frozen=True)
class ReviewedOffsetImport:
    """A saved file snapshot explicitly reviewed by the current writer."""

    money: ImportedCurrencyPayload
    category: str
    calendar_revision: int | None = None
    accounting_time: AccountingTimeSnapshot | None = None

    def command_body(self) -> dict[str, object]:
        snapshot = self.money
        return {"home_currency_code": snapshot.home_currency_code,
            "original_currency_code": snapshot.original_currency_code,
            "original_amount_minor": snapshot.original_amount_minor,
            "amount_cents": snapshot.amount_cents,
            "exchange_rate_to_cny": str(snapshot.exchange_rate_to_cny),
            "exchange_rate_date": snapshot.exchange_rate_date.isoformat() if snapshot.exchange_rate_date else None,
            "declared_exchange_rate_source": snapshot.exchange_rate_source,
            "category": self.category,
            **({"calendar_revision": self.calendar_revision} if self.calendar_revision is not None else {}),
            **({"accounting_time": self.accounting_time.model_dump(mode="json")} if self.accounting_time is not None else {})}

def _require_confirmed(expense: Expense) -> None:
    if expense.status == "confirmed" and expense.amount_cents is not None:
        return
    if expense.status == "pending":
        raise AppError("expense_not_confirmed", status_code=409)
    raise AppError("expense_not_found", status_code=404)


def _offset_snapshot(offset: ExpenseOffsetFact) -> dict[str, object]:
    time_snapshot = accounting_time_snapshot(offset)
    return {
        **({"accounting_time": time_snapshot.model_dump(mode="json")} if time_snapshot is not None else {}),
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
        "exchange_rate_date": (
            offset.exchange_rate_date.isoformat() if offset.exchange_rate_date is not None else None
        ),
        "exchange_rate_source": offset.exchange_rate_source,
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
    accepted_relationships: tuple[AcceptedSourceRelationship, ...] | None = None,
    cancelled_public_ids: tuple[str, ...] = (),
    cancellation_reason_code: str | None = None,
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
    summary = expense_financial_summary(expense, offsets)
    return ExpenseFactBundleResponse(
        root=expense_to_response(db, tenant_id=tenant_id, expense=expense),
        financial_summary=summary,
        active_offsets=[ExpenseOffsetResponse.model_validate(offset).model_copy(update={
            "accounting_time": accounting_time_snapshot(offset)}) for offset in offsets],
        recent_history=[
            _revision_to_response(
                db,
                revision,
                offset_public_id=offset_by_id[revision.offset_id],
            )
            for revision in revisions
        ],
        relationship_impacts=relationship_impacts(
            db,
            tenant_id=tenant_id,
            expense_id=expense.id,
            offsets=offsets,
            summary=summary,
            accepted_relationships=accepted_relationships,
            cancelled_public_ids=cancelled_public_ids,
            cancellation_reason_code=cancellation_reason_code,
        ),
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


def _claim_offset_command(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    payload: ExpenseOffsetCreateRequest,
    actor_account_id: int,
    idempotency_key: str | None,
    imported: ReviewedOffsetImport | None = None,
) -> ApiIdempotencyKey | ExpenseFactBundleResponse:
    claim = claim_idempotent_request(
        db,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        operation="create_expense_offset",
        target_id=str(expense_id),
        target_type="expense_offset",
        body={
            **payload.model_dump(mode="json", exclude={"expected_row_version"}),
            "actor_account_id": actor_account_id,
            **({"reviewed_import": imported.command_body()} if imported is not None else {}),
        },
        expected_row_version=payload.expected_row_version,
    )
    if claim is not None:
        return claim
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)
    return _replayed_bundle(
        db,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
    )


def _claim_expense_for_offset(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    expected_row_version: int,
) -> tuple[Expense, list[ExpenseOffsetFact], datetime]:
    current = get_expense(db, expense_id, tenant_id)
    _require_confirmed(current)
    now = now_utc()
    claimed = claim_row_with_token(
        db,
        Expense,
        pk_id=expense_id,
        tenant_id=tenant_id,
        expected_row_version=expected_row_version,
        set_values={"updated_at": now},
        extra_where=(Expense.status == "confirmed",),
        synchronize_session=False,
    )
    if claimed != 1:
        db.rollback()
        _require_confirmed(get_expense(db, expense_id, tenant_id))
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
    return expense, offsets, now


def _persist_new_offset(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
    payload: ExpenseOffsetCreateRequest,
    money: OffsetMoney,
    actor_account_id: int,
    actor_device_public_id: str | None,
    actor_device_name: str | None,
    idempotency_key: str,
    now: datetime,
    category: str | None = None,
    time_values: dict[str, object],
) -> ExpenseOffsetFact:
    offset = ExpenseOffsetFact(
        tenant_id=tenant_id,
        expense_id=expense.id,
        kind=payload.kind,
        original_currency_code=expense.original_currency_code,
        original_amount_minor=money.original_amount_minor,
        home_currency_code=expense.home_currency_code,
        amount_cents=money.amount_cents,
        exchange_rate_to_cny=money.exchange_rate_to_cny,
        exchange_rate_date=money.exchange_rate_date,
        exchange_rate_source=money.exchange_rate_source,
        **time_values,
        category=category if category is not None else expense.category,
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
    db.add(
        ExpenseOffsetRevision(
            tenant_id=tenant_id,
            expense_id=expense.id,
            offset_id=offset.id,
            revision_number=1,
            change_kind="created",
            reason=payload.reason,
            idempotency_key=idempotency_key,
            actor_account_id=actor_account_id,
            actor_device_public_id=actor_device_public_id,
            actor_device_name=actor_device_name,
            before_snapshot=None,
            after_snapshot=_offset_snapshot(offset),
            previous_row_version=None,
            resulting_row_version=offset.row_version,
            created_at=now,
        )
    )
    db.flush()
    return offset


def offset_accounting_values(db: Session, *, tenant_id: str, accounting_date: date,
                              imported: ReviewedOffsetImport | None = None) -> dict[str, object]:
    rule = (calendar_revision(db, ledger_id=tenant_id, revision=imported.calendar_revision or 1)
            if imported is not None else current_calendar(db, ledger_id=tenant_id))
    if rule is None:
        raise AppError("calendar_revision_conflict", status_code=409)
    snapshot = AccountingTimeSnapshot(precision="date_only", accounting_date=accounting_date,
        user_local_date=None if imported is not None else accounting_date, calendar_revision=rule.revision,
        basis="recorded_date" if imported is not None else "user_date")
    if imported is not None and imported.accounting_time is not None:
        snapshot = imported.accounting_time.model_copy(update={"calendar_revision": rule.revision, "basis": "recorded_date"})
        if snapshot.precision != "date_only" or snapshot.accounting_date != accounting_date or snapshot.instant_utc is not None:
            raise AppError("accounting_time_invalid", status_code=422)
    return {"accounting_date": snapshot.accounting_date, "calendar_revision": snapshot.calendar_revision,
        "user_local_date": snapshot.user_local_date, "time_precision": snapshot.precision,
        "source_timezone": snapshot.source_timezone, "source_utc_offset_seconds": snapshot.source_utc_offset_seconds,
        "accounting_date_basis": snapshot.basis}


def _commit_offset_creation(
    db: Session,
    *,
    claim: ApiIdempotencyKey,
    offset: ExpenseOffsetFact,
    result: ExpenseFactBundleResponse,
    commit: bool,
) -> ExpenseFactBundleResponse:
    mark_idempotency_succeeded(
        db,
        claim,
        resource_type="expense_offset",
        resource_id=offset.public_id,
        # Computed stream projections are reconstructed by the response model
        # on replay; storing them would make this strict model reject its own
        # receipt as extra input.
        response_body=result.model_dump(mode="json", exclude_computed_fields=True),
    )
    if commit:
        db.commit()
    return result


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
    imported: ReviewedOffsetImport | None = None,
    commit: bool = True,
) -> ExpenseFactBundleResponse:
    """Create one offset fact and publish its immutable first revision."""

    claim_or_replay = _claim_offset_command(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        payload=payload,
        actor_account_id=actor_account_id,
        idempotency_key=idempotency_key,
        imported=imported,
    )
    if isinstance(claim_or_replay, ExpenseFactBundleResponse):
        return claim_or_replay
    if idempotency_key is None:
        raise AppError("server_error", status_code=500)
    claim = claim_or_replay

    authorize_currency_metadata_write(db)
    expense, offsets, now = _claim_expense_for_offset(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        expected_row_version=effective_expected_row_version,
    )
    time_values = offset_accounting_values(db, tenant_id=tenant_id, accounting_date=payload.accounting_date,
        imported=imported)
    money = resolve_offset_money(
        db,
        tenant_id=tenant_id,
        expense=expense,
        offsets=offsets,
        payload=payload,
        imported_snapshot=imported.money if imported is not None else None,
    )
    offset = _persist_new_offset(
        db,
        tenant_id=tenant_id,
        expense=expense,
        payload=payload,
        money=money,
        actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id,
        actor_device_name=actor_device_name,
        idempotency_key=idempotency_key,
        now=now,
        category=imported.category if imported is not None else None,
        time_values=time_values,
    )
    reason_code = source_relationship_reason(payload.kind)
    relationship_result = settle_source_financial_change(
        db,
        sender_ledger_id=tenant_id,
        sender_expense_id=expense_id,
        reason_code=reason_code,
        actor_account_id=actor_account_id,
    )
    result = expense_fact_bundle(
        db,
        tenant_id=tenant_id,
        expense_id=expense_id,
        accepted_relationships=relationship_result.accepted_relationships,
        cancelled_public_ids=relationship_result.cancelled_public_ids,
        cancellation_reason_code=reason_code,
    )
    return _commit_offset_creation(
        db,
        claim=claim,
        offset=offset,
        result=result,
        commit=commit,
    )
