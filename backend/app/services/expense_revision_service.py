"""Confirmed Expense publication, correction history, and timeline reads."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Account, Device, Expense, ExpenseItem, ExpenseRevision, ExpenseSplit
from app.schemas import ExpenseRevisionListResponse, ExpenseRevisionResponse
from app.services.time_service import to_iso

CONFIRMED_REASON = "首次确认"

_SCALAR_FIELDS = (
    "amount_cents",
    "home_currency_code",
    "original_currency_code",
    "original_amount_minor",
    "exchange_rate_to_cny",
    "exchange_rate_date",
    "exchange_rate_source",
    "fx_status",
    "merchant",
    "category",
    "note",
    "source",
    "tags",
    "value_score",
    "regret_score",
    "expense_time",
    "confirmed_at",
    "items_sum_status",
)
_SNAPSHOT_FIELDS = (*_SCALAR_FIELDS, "items", "splits")


@dataclass(frozen=True)
class PreparedCorrectionRevision:
    """Revision input captured before an existing command mutates a fact."""

    before: dict[str, object]
    previous_row_version: int


def _json_value(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return to_iso(value) if hasattr(value, "tzinfo") else value.isoformat()
    return value


def expense_fact_snapshot(db: Session, expense: Expense) -> dict[str, object]:
    """Return the rebuildable v1 snapshot of user-visible financial fields."""

    snapshot: dict[str, object] = {field: _json_value(getattr(expense, field)) for field in _SCALAR_FIELDS}
    items = list(
        db.scalars(
            ledger_scoped_select(ExpenseItem, expense.tenant_id)
            .where(ExpenseItem.expense_id == expense.id)
            .order_by(ExpenseItem.position.asc(), ExpenseItem.id.asc())
        )
    )
    snapshot["items"] = [
        {
            "position": item.position,
            "kind": item.kind,
            "name": item.name,
            "quantity_text": item.quantity_text,
            "unit_price_cents": item.unit_price_cents,
            "amount_cents": item.amount_cents,
            "category": item.category,
            "raw_text": item.raw_text,
            "confidence": item.confidence,
        }
        for item in items
    ]
    splits = list(
        db.scalars(
            ledger_scoped_select(ExpenseSplit, expense.tenant_id)
            .where(ExpenseSplit.expense_id == expense.id)
            .order_by(ExpenseSplit.position.asc(), ExpenseSplit.id.asc())
        )
    )
    snapshot["splits"] = [
        {
            "position": split.position,
            "member_id": split.member_id,
            "amount_cents": split.amount_cents,
            "note": split.note,
        }
        for split in splits
    ]
    return snapshot


def changed_fact_fields(before: dict[str, object], after: dict[str, object]) -> list[str]:
    return [field for field in _SNAPSHOT_FIELDS if before.get(field) != after.get(field)]


def _device_snapshot(
    db: Session,
    actor_device_id: int | None,
) -> tuple[str | None, str | None]:
    if actor_device_id is None:
        return None, None
    device = db.execute(select(Device.public_id, Device.device_name).where(Device.id == actor_device_id)).one_or_none()
    if device is None:
        raise AppError("state_conflict", status_code=409)
    return device.public_id, device.device_name


def record_confirmation_revision(
    db: Session,
    expense: Expense,
    *,
    actor_account_id: int | None,
    actor_device_id: int | None,
    idempotency_key: str | None = None,
) -> ExpenseRevision:
    """Publish revision 1 exactly once for a newly confirmed fact."""

    existing = db.scalar(
        ledger_scoped_select(ExpenseRevision, expense.tenant_id)
        .where(ExpenseRevision.expense_id == expense.id)
        .order_by(ExpenseRevision.revision_number.asc())
        .limit(1)
    )
    if existing is not None:
        return existing
    if expense.confirmed_at is None:
        raise AppError("state_conflict", status_code=409)
    db.flush()
    if not isinstance(expense.row_version, int):
        db.refresh(expense)
    expense.fact_revision = 1
    actor_device_public_id, actor_device_name = _device_snapshot(db, actor_device_id)
    revision = ExpenseRevision(
        tenant_id=expense.tenant_id,
        expense_id=expense.id,
        revision_number=1,
        change_kind="confirmed",
        reason=CONFIRMED_REASON,
        idempotency_key=idempotency_key,
        actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id,
        actor_device_name=actor_device_name,
        changed_fields=list(_SNAPSHOT_FIELDS),
        before_snapshot=None,
        after_snapshot=expense_fact_snapshot(db, expense),
        previous_row_version=None,
        resulting_row_version=expense.row_version,
    )
    db.add(revision)
    db.flush()
    return revision


def record_correction_revision(
    db: Session,
    expense: Expense,
    *,
    before: dict[str, object],
    previous_row_version: int,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
    idempotency_key: str | None,
) -> ExpenseRevision:
    """Append one correction after the current projection has been updated."""

    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise AppError("expense_correction_reason_required", status_code=422)
    db.flush()
    db.refresh(expense)
    after = expense_fact_snapshot(db, expense)
    changed_fields = changed_fact_fields(before, after)
    if not changed_fields:
        raise AppError("expense_correction_no_changes", status_code=422)
    actor_device_public_id, actor_device_name = _device_snapshot(db, actor_device_id)
    revision = ExpenseRevision(
        tenant_id=expense.tenant_id,
        expense_id=expense.id,
        revision_number=expense.fact_revision,
        change_kind="correction",
        reason=cleaned_reason,
        idempotency_key=idempotency_key,
        actor_account_id=actor_account_id,
        actor_device_public_id=actor_device_public_id,
        actor_device_name=actor_device_name,
        changed_fields=changed_fields,
        before_snapshot=before,
        after_snapshot=after,
        previous_row_version=previous_row_version,
        resulting_row_version=expense.row_version,
    )
    db.add(revision)
    db.flush()
    return revision


def prepare_correction_revision(
    db: Session,
    expense: Expense,
) -> PreparedCorrectionRevision | None:
    """Capture a published fact before an existing command changes it.

    ``confirmed_at`` is the publication boundary: a legacy row may currently be
    rejected and still belong to confirmed financial history.  Only rows that
    have never been published keep pending/rejected draft semantics and return
    ``None``. Legacy published rows receive revision 1 before the caller's own
    CAS/write when the migration backfill has not already created it.
    """

    if expense.confirmed_at is None:
        return None
    if expense.fact_revision == 0:
        record_confirmation_revision(
            db,
            expense,
            actor_account_id=None,
            actor_device_id=None,
        )
    return PreparedCorrectionRevision(
        before=expense_fact_snapshot(db, expense),
        previous_row_version=expense.row_version,
    )


def record_prepared_correction_revision(
    db: Session,
    expense: Expense,
    prepared: PreparedCorrectionRevision | None,
    *,
    reason: str,
    actor_account_id: int | None,
    actor_device_id: int | None,
    idempotency_key: str | None = None,
) -> ExpenseRevision | None:
    """Append the revision captured by :func:`prepare_correction_revision`."""

    if prepared is None:
        return None
    return record_correction_revision(
        db,
        expense,
        before=prepared.before,
        previous_row_version=prepared.previous_row_version,
        reason=reason,
        actor_account_id=actor_account_id,
        actor_device_id=actor_device_id,
        idempotency_key=idempotency_key,
    )


def revision_by_idempotency_key(db: Session, *, tenant_id: str, idempotency_key: str) -> ExpenseRevision | None:
    return db.scalar(
        ledger_scoped_select(ExpenseRevision, tenant_id).where(ExpenseRevision.idempotency_key == idempotency_key)
    )


def revision_to_response(db: Session, revision: ExpenseRevision) -> ExpenseRevisionResponse:
    account_name = None
    if revision.actor_account_id is not None:
        account_name = db.scalar(select(Account.display_name).where(Account.id == revision.actor_account_id))
    return ExpenseRevisionResponse(
        public_id=revision.public_id,
        revision_number=revision.revision_number,
        change_kind=revision.change_kind,
        reason=revision.reason,
        changed_fields=list(revision.changed_fields),
        before=revision.before_snapshot,
        after=revision.after_snapshot,
        actor_account_name=account_name,
        actor_device_name=revision.actor_device_name,
        created_at=revision.created_at,
    )


def list_expense_revisions(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    current_revision: int,
    snapshot_revision: int | None,
    page: int,
    page_size: int,
) -> ExpenseRevisionListResponse:
    # The parent lookup belongs to the caller so a foreign tenant and a missing
    # expense share the existing expense_not_found contract.
    effective_snapshot = current_revision if snapshot_revision is None else min(snapshot_revision, current_revision)
    filters = (
        ExpenseRevision.tenant_id == tenant_id,
        ExpenseRevision.expense_id == expense_id,
        ExpenseRevision.revision_number <= effective_snapshot,
    )
    total = int(db.scalar(select(func.count()).select_from(ExpenseRevision).where(*filters)) or 0)
    rows = list(
        db.scalars(
            select(ExpenseRevision)
            .where(*filters)
            .order_by(ExpenseRevision.revision_number.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return ExpenseRevisionListResponse(
        items=[revision_to_response(db, row) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        snapshot_revision=effective_snapshot,
    )
