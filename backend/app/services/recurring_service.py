from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import RecurringItem
from app.schemas import RecurringCandidateConfirmRequest, RecurringItemResponse
from app.services.insights_service import normalize_merchant, recurring_candidates
from app.services.time_service import ensure_utc, now_utc


VALID_FREQUENCIES = {"monthly"}
VALID_STATUSES = {"active", "paused", "archived"}


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


def _next_expected_date(last_seen_at: datetime | None) -> date | None:
    if last_seen_at is None:
        return None
    return _add_one_month(last_seen_at.date())


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
        select(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.merchant_key == merchant_key)
        .where(RecurringItem.frequency == frequency)
        .limit(1)
    )


def recurring_item_response(item: RecurringItem) -> RecurringItemResponse:
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
        created_at=item.created_at,
        updated_at=item.updated_at,
        paused_at=item.paused_at,
        archived_at=item.archived_at,
    )


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
        next_expected_date=payload.next_expected_date or _next_expected_date(last_seen_at),
        status="active",
        confidence=str(confidence) if confidence else None,
        source="candidate",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_recurring_items(
    db: Session,
    *,
    tenant_id: str,
    status: str | None = None,
    include_archived: bool = False,
) -> list[RecurringItem]:
    statement = select(RecurringItem).where(RecurringItem.tenant_id == tenant_id)
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
        select(RecurringItem)
        .where(RecurringItem.tenant_id == tenant_id)
        .where(RecurringItem.public_id == public_id)
        .limit(1)
    )
    if item is None:
        raise AppError("recurring_item_not_found", status_code=404)
    return item


def pause_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status == "archived":
        raise AppError("recurring_item_archived", status_code=409)
    if item.status != "paused":
        now = now_utc()
        item.status = "paused"
        item.paused_at = now
        item.updated_at = now
        db.commit()
        db.refresh(item)
    return item


def resume_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status == "archived":
        raise AppError("recurring_item_archived", status_code=409)
    if item.status != "active":
        now = now_utc()
        item.status = "active"
        item.paused_at = None
        item.updated_at = now
        db.commit()
        db.refresh(item)
    return item


def archive_recurring_item(db: Session, *, tenant_id: str, public_id: str) -> RecurringItem:
    item = get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
    if item.status != "archived":
        now = now_utc()
        item.status = "archived"
        item.archived_at = now
        item.updated_at = now
        db.commit()
        db.refresh(item)
    return item
