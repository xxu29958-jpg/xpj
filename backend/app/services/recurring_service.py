from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Expense, RecurringItem
from app.schemas import RecurringCandidateConfirmRequest, RecurringItemResponse
from app.services.insights_service import normalize_merchant, recurring_candidates
from app.services.optimistic_concurrency import bump_row_version
from app.services.spending_contract_service import current_accounting_month, month_bounds_utc, stat_time
from app.services.time_service import ensure_utc, now_utc, safe_zone

VALID_FREQUENCIES = {"monthly"}
VALID_STATUSES = {"active", "paused", "archived"}
ANOMALY_THRESHOLD_PERCENT = 30
RECURRING_AMOUNT_MATCH_MAX_DELTA_PERCENT = 100


@dataclass(frozen=True)
class RecurringAmountAnomaly:
    anomaly_status: str = "none"
    current_month_amount_cents: int | None = None
    historical_average_amount_cents: int | None = None
    amount_delta_percent: int | None = None


def _clean_frequency(value: str | None) -> str:
    frequency = (value or "monthly").strip()
    if frequency not in VALID_FREQUENCIES:
        raise AppError("recurring_frequency_invalid", status_code=422)
    return frequency


def _clean_status(value: str | None) -> str:
    status = (value or "").strip()
    if status not in VALID_STATUSES:
        raise AppError("recurring_status_invalid", status_code=422)
    return status


def _add_one_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _next_expected_date(last_seen_at: datetime | None, timezone_name: str | None) -> date | None:
    utc_value = ensure_utc(last_seen_at)
    if utc_value is None:
        return None
    resolved_timezone = (timezone_name or "").strip() or get_settings().ocr_default_timezone
    local_date = utc_value.astimezone(safe_zone(resolved_timezone)).date()
    return _add_one_month(local_date)


def _find_recurring_candidate(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
    amount_cents: int,
    timezone_name: str | None,
) -> dict | None:
    for item in recurring_candidates(db, tenant_id=tenant_id, timezone_name=timezone_name):
        if normalize_merchant(item.get("merchant")) != merchant_key:
            continue
        if int(item.get("amount_cents") or 0) != amount_cents:
            continue
        return item
    return None


def _existing_item(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
    frequency: str,
) -> RecurringItem | None:
    return db.scalar(
        ledger_scoped_select(RecurringItem, tenant_id)
        .where(RecurringItem.merchant_key == merchant_key)
        .where(RecurringItem.frequency == frequency)
        .limit(1)
    )


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
        baseline_amount_cents=item.baseline_amount_cents,
        last_amount_cents=item.last_amount_cents,
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
        amount = int(expense.amount_cents or 0)
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
        average_amount = int(round(sum(history) / len(history))) if history else int(item.baseline_amount_cents)
        if average_amount <= 0:
            continue
        delta_percent = int(round((latest_amount - average_amount) * 100 / average_amount))
        status = "higher_than_average" if delta_percent >= threshold_percent else "none"
        anomalies[item.public_id] = RecurringAmountAnomaly(
            anomaly_status=status,
            current_month_amount_cents=latest_amount,
            historical_average_amount_cents=average_amount,
            amount_delta_percent=delta_percent,
        )
    return anomalies


def _is_recurring_like_amount(item: RecurringItem, amount_cents: int) -> bool:
    reference = max(int(item.last_amount_cents or 0), int(item.baseline_amount_cents or 0))
    if reference <= 0:
        return False
    delta_percent = abs(amount_cents - reference) * 100 / reference
    return delta_percent <= RECURRING_AMOUNT_MATCH_MAX_DELTA_PERCENT


def confirm_recurring_candidate(
    db: Session,
    *,
    tenant_id: str,
    payload: RecurringCandidateConfirmRequest,
    timezone_name: str | None = None,
) -> RecurringItem:
    merchant = payload.merchant.strip()
    merchant_key = normalize_merchant(merchant)
    if not merchant_key:
        raise AppError("recurring_candidate_not_found", status_code=404)
    frequency = _clean_frequency(payload.frequency)
    amount_cents = int(payload.amount_cents)

    candidate = _find_recurring_candidate(
        db,
        tenant_id=tenant_id,
        merchant_key=merchant_key,
        amount_cents=amount_cents,
        timezone_name=timezone_name,
    )
    if candidate is None:
        raise AppError("recurring_candidate_not_found", status_code=404)

    existing = _existing_item(
        db,
        tenant_id=tenant_id,
        merchant_key=merchant_key,
        frequency=frequency,
    )
    if existing is not None:
        if existing.status == "archived" or existing.archived_at is not None:
            last_seen_at = ensure_utc(payload.last_seen_at) or ensure_utc(candidate.get("last_seen_at"))
            confidence = payload.confidence or candidate.get("confidence")
            now = now_utc()
            existing.merchant_name = str(candidate.get("merchant") or merchant)
            existing.baseline_amount_cents = amount_cents
            existing.last_amount_cents = amount_cents
            existing.occurrence_count = max(
                int(payload.occurrence_count or 0),
                int(candidate.get("occurrence_count") or 0),
                int(existing.occurrence_count or 0),
            )
            existing.last_seen_at = last_seen_at
            existing.next_expected_date = payload.next_expected_date or _next_expected_date(last_seen_at, timezone_name)
            existing.status = "active"
            existing.confidence = str(confidence) if confidence else None
            existing.source = "candidate"
            existing.paused_at = None
            existing.archived_at = None
            existing.updated_at = now
            bump_row_version(existing)
            db.commit()
            db.refresh(existing)
        return existing

    last_seen_at = ensure_utc(payload.last_seen_at) or ensure_utc(candidate.get("last_seen_at"))
    confidence = payload.confidence or candidate.get("confidence")
    now = now_utc()
    item = RecurringItem(
        tenant_id=tenant_id,
        merchant_key=merchant_key,
        merchant_name=str(candidate.get("merchant") or merchant),
        frequency=frequency,
        baseline_amount_cents=amount_cents,
        last_amount_cents=amount_cents,
        occurrence_count=max(int(payload.occurrence_count or 0), int(candidate.get("occurrence_count") or 0)),
        last_seen_at=last_seen_at,
        next_expected_date=payload.next_expected_date or _next_expected_date(last_seen_at, timezone_name),
        status="active",
        confidence=str(confidence) if confidence else None,
        source="candidate",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_after_race = _existing_item(
            db,
            tenant_id=tenant_id,
            merchant_key=merchant_key,
            frequency=frequency,
        )
        if existing_after_race is not None:
            return existing_after_race
        raise
    db.refresh(item)
    return item


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
        ledger_scoped_select(RecurringItem, tenant_id)
        .where(RecurringItem.public_id == public_id)
        .limit(1)
    )
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    return item


def pause_recurring_item(
    db: Session, *, tenant_id: str, public_id: str, expected_row_version: int
) -> RecurringItem:
    """ADR-0038 PR-A: pause with optimistic concurrency.

    pause and resume are a state-machine toggle pair — stale pause arriving
    after a user-intentional resume would silently re-pause without OCC
    (atomic UPDATE WHERE status!='archived' would match either state).
    Token check rejects the stale request.
    """
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
        raise AppError("recurring_item_archived", status_code=409)
    raise AppError("state_conflict", status_code=409)


def resume_recurring_item(
    db: Session, *, tenant_id: str, public_id: str, expected_row_version: int
) -> RecurringItem:
    """ADR-0038 PR-A: resume with optimistic concurrency. Same rationale
    as :func:`pause_recurring_item`."""
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
        raise AppError("recurring_item_archived", status_code=409)
    raise AppError("state_conflict", status_code=409)


def restore_recurring_item(
    db: Session, *, tenant_id: str, public_id: str, expected_row_version: int
) -> RecurringItem:
    """ADR-0051 recycle-bin restore: reactivate an archived recurring item.

    Inverse of :func:`archive_recurring_item` but OCC-gated like the
    :func:`resume_recurring_item` toggle: the atomic ``UPDATE ... WHERE
    status='archived', row_version=expected`` only matches a still-archived row
    carrying the client's last-seen token. ``paused_at`` is cleared so a
    restored item lands cleanly ``active`` (mirrors candidate reactivation).
    Idempotent on an already-active item (404 only when absent); a stale token
    against an archived item is 409 ``state_conflict``.
    """
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status != "archived":
        return item  # not in the recycle bin — nothing to restore
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
    if current.status != "archived":
        return current  # raced into active — idempotent restore
    raise AppError("state_conflict", status_code=409)


def archive_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
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
