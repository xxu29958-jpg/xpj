"""Append within existing series transactions and read the original recorded basis."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import RecurringItem, RecurringItemRevision, RecurringOccurrence
from app.schemas._recurring_history import (
    RecordedRecurringDefinition,
    RecurringItemHistoryResponse,
    RecurringItemRevisionResponse,
    RecurringItemSnapshot,
)
from app.services.time_service import now_utc


def lock_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = db.scalar(ledger_scoped_select(RecurringItem, tenant_id).where(RecurringItem.public_id == public_id)
        .with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    return item


def record_recurring_item_revision(db: Session, item: RecurringItem, *, change_kind: str,
    actor_account_id: int | None = None) -> RecurringItemRevision:
    snapshot = RecurringItemSnapshot(merchant=item.merchant_name, merchant_key=item.merchant_key,
        frequency=item.frequency, home_currency_code=item.home_currency_code,
        baseline_amount_cents=item.baseline_amount_cents, next_expected_date=item.next_expected_date,
        status=item.status, source=item.source)
    revision = RecurringItemRevision(tenant_id=item.tenant_id, series_id=item.id, row_version=item.row_version,
        change_kind=change_kind, snapshot=snapshot.model_dump(mode="json"),
        actor_account_id=actor_account_id, recorded_at=now_utc())
    db.add(revision)
    return revision


def ensure_recurring_history_baseline(db: Session, item: RecurringItem) -> RecurringItemRevision:
    # The caller holds the series row lock. Never reconstruct earlier revisions.
    revision = db.scalar(select(RecurringItemRevision).where(RecurringItemRevision.tenant_id == item.tenant_id,
        RecurringItemRevision.series_id == item.id, RecurringItemRevision.row_version == item.row_version))
    if revision is None:
        revision = record_recurring_item_revision(db, item, change_kind="baseline")
        db.flush()
    return revision


def recurring_item_history(db: Session, *, tenant_id: str, public_id: str,
    before_version: int | None = None, limit: int = 20) -> RecurringItemHistoryResponse:
    item = db.scalar(ledger_scoped_select(RecurringItem, tenant_id).where(RecurringItem.public_id == public_id))
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    query = select(RecurringItemRevision).where(RecurringItemRevision.tenant_id == tenant_id,
        RecurringItemRevision.series_id == item.id)
    if before_version is not None:
        query = query.where(RecurringItemRevision.row_version < before_version)
    rows = db.scalars(query.order_by(RecurringItemRevision.row_version.desc()).limit(limit + 1)).all()
    selected = rows[:limit]
    return RecurringItemHistoryResponse(ledger_id=tenant_id, public_id=public_id,
        items=[RecurringItemRevisionResponse(row_version=row.row_version, change_kind=row.change_kind,
            recorded_at=row.recorded_at, actor_account_id=row.actor_account_id,
            snapshot=RecurringItemSnapshot.model_validate(row.snapshot)) for row in selected],
        next_before_version=selected[-1].row_version if len(rows) > limit else None)


def recorded_occurrence_definition(db: Session, row: RecurringOccurrence | None) -> RecordedRecurringDefinition | None:
    if row is None or row.recorded_definition_row_version is None:
        return None
    revision = db.scalar(select(RecurringItemRevision).where(RecurringItemRevision.tenant_id == row.tenant_id,
        RecurringItemRevision.series_id == row.series_id,
        RecurringItemRevision.row_version == row.recorded_definition_row_version))
    if revision is None:
        raise AppError("state_conflict", "本期记录的原定义不可用，请核对固定支出历史。", status_code=409)
    return RecordedRecurringDefinition(series_row_version=revision.row_version, recorded_at=row.definition_recorded_at,
        snapshot=RecurringItemSnapshot.model_validate(revision.snapshot))
