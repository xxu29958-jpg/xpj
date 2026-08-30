from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, RecurringItem
from app.money_contract import (
    projection_sum_to_int,
    projection_values_average_to_int,
    round_minor_ratio_half_up,
)
from app.schemas import RecurringItemResponse
from app.services.currency_binding_service import resolve_write_capability
from app.services.merchant_service import normalize_merchant
from app.services.spending_contract_service import current_accounting_month, month_bounds_utc, stat_time
from app.services.time_service import now_utc

VALID_STATUSES = {"active", "paused", "archived"}
ANOMALY_THRESHOLD_PERCENT = 30
RECURRING_AMOUNT_MATCH_MAX_DELTA_PERCENT = 100


def recurring_item_monthly_detail(item: RecurringItem, amount_label: str) -> str:
    """Describe the plan without presenting a manual compatibility seed as observation."""
    detail = f"每月 {amount_label}"
    if item.occurrence_count > 0:
        detail += f" · 已出现 {item.occurrence_count} 次"
    return detail


@dataclass(frozen=True)
class RecurringAmountAnomaly:
    anomaly_status: str = "none"
    current_month_amount_cents: int | None = None
    historical_average_amount_cents: int | None = None
    amount_delta_percent: int | None = None


def _clean_status(value: str | None) -> str:
    status = (value or "").strip()
    if status not in VALID_STATUSES:
        raise AppError("recurring_status_invalid", status_code=422)
    return status


def recurring_item_response(
    item: RecurringItem,
    anomaly: RecurringAmountAnomaly | None = None,
) -> RecurringItemResponse:
    amount_anomaly = anomaly or RecurringAmountAnomaly()
    return RecurringItemResponse(
        public_id=item.public_id,
        ledger_id=item.tenant_id,
        merchant=item.merchant_name,
        merchant_key=item.merchant_key,
        frequency=item.frequency,
        baseline_amount_cents=projection_sum_to_int(
            item.baseline_amount_cents,
            label="recurring.response_baseline",
        ),
        last_amount_cents=projection_sum_to_int(
            item.last_amount_cents,
            label="recurring.response_last",
        ),
        occurrence_count=item.occurrence_count,
        last_seen_at=item.last_seen_at,
        next_expected_date=item.next_expected_date,
        status=item.status,
        confidence=item.confidence,
        source=item.source,
        anomaly_status=amount_anomaly.anomaly_status,
        current_month_amount_cents=amount_anomaly.current_month_amount_cents,
        historical_average_amount_cents=amount_anomaly.historical_average_amount_cents,
        amount_delta_percent=amount_anomaly.amount_delta_percent,
        created_at=item.created_at,
        updated_at=item.updated_at,
        row_version=item.row_version,
        paused_at=item.paused_at,
        archived_at=item.archived_at,
    )


def _historical_average_amount(item: RecurringItem, history: list[int]) -> int:
    if not history:
        return projection_sum_to_int(
            item.baseline_amount_cents,
            label="recurring.baseline",
        )
    return projection_values_average_to_int(
        history,
        label="recurring.history_average",
    )


def recurring_amount_anomalies(
    db: Session,
    *,
    tenant_id: str,
    items: list[RecurringItem],
    month: str | None = None,
    timezone_name: str | None = None,
    threshold_percent: int = ANOMALY_THRESHOLD_PERCENT,
) -> dict[str, RecurringAmountAnomaly]:
    active_items = [item for item in items if item.status == "active"]
    merchant_keys = {item.merchant_key for item in active_items}
    merchant_names = {item.merchant_name for item in active_items}
    if not merchant_keys:
        return {}

    start_utc, end_utc = month_bounds_utc(
        month or current_accounting_month(timezone_name),
        timezone_name,
    )

    active_by_key = {item.merchant_key: item for item in active_items}
    history_amounts: dict[str, list[int]] = {key: [] for key in merchant_keys}
    current_entries: dict[str, list[tuple[datetime, int]]] = {key: [] for key in merchant_keys}
    expenses = db.scalars(
        select(Expense)
        .where(Expense.tenant_id == tenant_id)
        .where(Expense.status == "confirmed")
        .where(Expense.merchant.is_not(None))
        .where(Expense.amount_cents.is_not(None))
        .where(
            or_(
                Expense.merchant.in_(merchant_names),
                func.lower(func.trim(Expense.merchant)).in_(merchant_keys),
            )
        )
    )
    for expense in expenses:
        key = normalize_merchant(expense.merchant)
        if key not in merchant_keys:
            continue
        when = stat_time(expense)
        if when is None:
            continue
        amount = projection_sum_to_int(
            expense.amount_cents,
            label="recurring.expense",
        )
        if amount <= 0:
            continue
        item = active_by_key.get(key)
        if item is None or not _is_recurring_like_amount(item, amount):
            continue
        if start_utc <= when < end_utc:
            current_entries[key].append((when, amount))
        elif when < start_utc:
            history_amounts[key].append(amount)

    anomalies: dict[str, RecurringAmountAnomaly] = {}
    for item in active_items:
        current = current_entries.get(item.merchant_key) or []
        if not current:
            continue
        latest_amount = sorted(current, key=lambda pair: pair[0])[-1][1]
        history = history_amounts.get(item.merchant_key) or []
        average_amount = _historical_average_amount(item, history)
        if average_amount <= 0:
            continue
        delta_percent = round_minor_ratio_half_up(
            (latest_amount - average_amount) * 100,
            average_amount,
            label="recurring.delta_percent",
        )
        status = "higher_than_average" if delta_percent >= threshold_percent else "none"
        anomalies[item.public_id] = RecurringAmountAnomaly(
            anomaly_status=status,
            current_month_amount_cents=latest_amount,
            historical_average_amount_cents=average_amount,
            amount_delta_percent=delta_percent,
        )
    return anomalies


def _is_recurring_like_amount(item: RecurringItem, amount_cents: int) -> bool:
    reference = max(
        projection_sum_to_int(
            item.last_amount_cents,
            label="recurring.last_amount",
        ),
        projection_sum_to_int(
            item.baseline_amount_cents,
            label="recurring.baseline_amount",
        ),
    )
    if reference <= 0:
        return False
    return abs(amount_cents - reference) * 100 <= reference * RECURRING_AMOUNT_MATCH_MAX_DELTA_PERCENT


def list_recurring_items(
    db: Session,
    *,
    tenant_id: str,
    status: str | None = None,
    include_archived: bool = False,
) -> list[RecurringItem]:
    statement = ledger_scoped_select(RecurringItem, tenant_id)
    if status:
        statement = statement.where(RecurringItem.status == _clean_status(status))
    elif not include_archived:
        statement = statement.where(RecurringItem.status != "archived")
    statement = statement.order_by(
        RecurringItem.status.asc(),
        RecurringItem.next_expected_date.asc(),
        RecurringItem.merchant_name.asc(),
    )
    return list(db.scalars(statement))


def get_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = db.scalar(
        ledger_scoped_select(RecurringItem, tenant_id).where(RecurringItem.public_id == public_id).limit(1)
    )
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    return item


def pause_recurring_item(db: Session, *, tenant_id: str, public_id: str, expected_row_version: int) -> RecurringItem:
    """ADR-0038 PR-A: pause with optimistic concurrency.

    pause and resume are a state-machine toggle pair — stale pause arriving
    after a user-intentional resume would silently re-pause without OCC
    (atomic UPDATE WHERE status!='archived' would match either state).
    Token check rejects the stale request.
    """
    resolve_write_capability(db)
    now = now_utc()
    result = db.execute(
        update(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.public_id == public_id)
        .where(RecurringItem.status != "archived")
        .where(RecurringItem.archived_at.is_(None))
        .where(RecurringItem.row_version == expected_row_version)
        .values(
            status="paused",
            paused_at=now,
            updated_at=now,
            row_version=RecurringItem.row_version + 1,
        )
    )
    if result.rowcount:
        db.commit()
        return get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    db.rollback()
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status == "archived" or item.archived_at is not None:
        raise AppError(
            "recurring_item_archived",
            status_code=409,
            details={"public_id": item.public_id, "status": item.status},
        )
    raise AppError("state_conflict", status_code=409)


def resume_recurring_item(db: Session, *, tenant_id: str, public_id: str, expected_row_version: int) -> RecurringItem:
    """ADR-0038 PR-A: resume with optimistic concurrency. Same rationale
    as :func:`pause_recurring_item`."""
    resolve_write_capability(db)
    now = now_utc()
    result = db.execute(
        update(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.public_id == public_id)
        .where(RecurringItem.status != "archived")
        .where(RecurringItem.archived_at.is_(None))
        .where(RecurringItem.row_version == expected_row_version)
        .values(
            status="active",
            paused_at=None,
            updated_at=now,
            row_version=RecurringItem.row_version + 1,
        )
    )
    if result.rowcount:
        db.commit()
        return get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    db.rollback()
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status == "archived" or item.archived_at is not None:
        raise AppError(
            "recurring_item_archived",
            status_code=409,
            details={"public_id": item.public_id, "status": item.status},
        )
    raise AppError("state_conflict", status_code=409)


def restore_recurring_item(db: Session, *, tenant_id: str, public_id: str, expected_row_version: int) -> RecurringItem:
    """ADR-0051 recycle-bin restore: reactivate an archived recurring item.

    Inverse of :func:`archive_recurring_item` but OCC-gated like the
    :func:`resume_recurring_item` toggle: the atomic ``UPDATE ... WHERE
    status='archived', row_version=expected`` only matches a still-archived row
    carrying the client's last-seen token. ``paused_at`` is cleared so a
    restored item lands cleanly ``active`` (mirrors candidate reactivation).
    Idempotent on an already-active item (404 only when absent). ``paused`` is
    a later, user-owned fact and must never be reported as a successful restore;
    stale tokens against archived or paused items are 409 ``state_conflict``.
    """
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status == "active" and item.archived_at is None:
        return item
    if item.status != "archived":
        raise AppError("state_conflict", status_code=409)
    resolve_write_capability(db)
    now = now_utc()
    result = db.execute(
        update(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.public_id == public_id)
        .where(RecurringItem.status == "archived")
        .where(RecurringItem.row_version == expected_row_version)
        .values(
            status="active",
            archived_at=None,
            paused_at=None,
            updated_at=now,
            row_version=RecurringItem.row_version + 1,
        )
    )
    if result.rowcount:
        db.commit()
        return get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    db.rollback()
    current = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if current.status == "active" and current.archived_at is None:
        return current  # raced into the requested state — idempotent restore
    raise AppError("state_conflict", status_code=409)


def archive_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status == "archived":
        return item
    resolve_write_capability(db)
    now = now_utc()
    result = db.execute(
        update(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.public_id == public_id)
        .where(RecurringItem.status != "archived")
        .values(
            status="archived",
            archived_at=now,
            updated_at=now,
            row_version=RecurringItem.row_version + 1,
        )
    )
    if result.rowcount:
        db.commit()
    else:
        db.rollback()
    return get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
