from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import RecurringItem
from app.schemas import RecurringCandidateConfirmRequest
from app.services.insights_service import normalize_merchant, recurring_candidates
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import ensure_utc, now_utc, safe_zone

_VALID_FREQUENCIES = {"monthly"}


@dataclass(frozen=True)
class _RecurringCandidateMatch:
    merchant: str
    merchant_key: str
    frequency: str
    amount_cents: int
    candidate: dict


def _idempotent_formal_match(
    db: Session,
    *,
    tenant_id: str,
    merchant_key: str,
    frequency: str,
    amount_cents: int,
) -> RecurringItem | None:
    """已 formal (非 archived) 且金额一致的既有项——幂等返回的命中条件。

    复审 agent-60/R5: 金额匹配是守卫的一部分, 两处 (前置幂等/并发兜底) 共用,
    防止漂移。
    """
    formal = _existing_item(db, tenant_id=tenant_id, merchant_key=merchant_key, frequency=frequency)
    if (
        formal is not None
        and formal.status != "archived"
        and formal.archived_at is None
        and int(formal.last_amount_cents) == amount_cents
    ):
        return formal
    return None


def confirm_recurring_candidate(
    db: Session,
    *,
    tenant_id: str,
    payload: RecurringCandidateConfirmRequest,
    timezone_name: str | None = None,
) -> RecurringItem:
    # PR #253 R4: 候选装配已过滤 active/paused formal — 确认成功后候选自然消失,
    # 重试同一确认时走既有幂等返回 (不 404/409)。
    # 复审 agent-60: 幂等匹配必须含金额——已 formal 商家以不同金额重试时
    # 继续走候选匹配原路径 (恢复 404 守卫), 不静默返回既有项。
    merchant_key = normalize_merchant(payload.merchant.strip())
    frequency = _clean_frequency(payload.frequency)
    amount_cents = int(payload.amount_cents)
    if merchant_key:
        formal = _idempotent_formal_match(
            db,
            tenant_id=tenant_id,
            merchant_key=merchant_key,
            frequency=frequency,
            amount_cents=amount_cents,
        )
        if formal is not None:
            return formal
    try:
        match = _require_recurring_candidate_match(
            db,
            tenant_id=tenant_id,
            payload=payload,
            timezone_name=timezone_name,
        )
    except AppError as exc:
        # 并发兜底 (R5): 双请求确认同一 candidate, 本请求的前置检查读到对方提交前
        # 快照, candidate 查找读到对方提交后 (已被 claimed 过滤) — 按
        # (merchant_key, frequency, amount_cents) 复查 formal, 命中即幂等返回,
        # 未命中才是真的 not_found。
        if exc.error != "recurring_candidate_not_found":
            raise
        if not merchant_key:
            raise
        formal = _idempotent_formal_match(
            db,
            tenant_id=tenant_id,
            merchant_key=merchant_key,
            frequency=frequency,
            amount_cents=amount_cents,
        )
        if formal is not None:
            return formal
        raise
    existing = _existing_item(
        db,
        tenant_id=tenant_id,
        merchant_key=match.merchant_key,
        frequency=match.frequency,
    )
    if existing is not None:
        return _confirm_existing_recurring_item(
            db,
            existing,
            match=match,
            payload=payload,
            timezone_name=timezone_name,
        )
    return _create_recurring_item_from_candidate(
        db,
        tenant_id=tenant_id,
        match=match,
        payload=payload,
        timezone_name=timezone_name,
    )


def _require_recurring_candidate_match(
    db: Session,
    *,
    tenant_id: str,
    payload: RecurringCandidateConfirmRequest,
    timezone_name: str | None,
) -> _RecurringCandidateMatch:
    merchant = payload.merchant.strip()
    merchant_key = normalize_merchant(merchant)
    if not merchant_key:
        raise AppError("recurring_candidate_not_found", status_code=404)

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

    return _RecurringCandidateMatch(
        merchant=merchant,
        merchant_key=merchant_key,
        frequency=_clean_frequency(payload.frequency),
        amount_cents=amount_cents,
        candidate=candidate,
    )


def _confirm_existing_recurring_item(
    db: Session,
    existing: RecurringItem,
    *,
    match: _RecurringCandidateMatch,
    payload: RecurringCandidateConfirmRequest,
    timezone_name: str | None,
) -> RecurringItem:
    if existing.status != "archived" and existing.archived_at is None:
        return existing
    return _reactivate_recurring_item_from_candidate(
        db,
        existing,
        match=match,
        payload=payload,
        timezone_name=timezone_name,
    )


def _reactivate_recurring_item_from_candidate(
    db: Session,
    existing: RecurringItem,
    *,
    match: _RecurringCandidateMatch,
    payload: RecurringCandidateConfirmRequest,
    timezone_name: str | None,
) -> RecurringItem:
    last_seen_at = _candidate_last_seen_at(payload, match)
    confidence = _candidate_confidence(payload, match)
    now = now_utc()
    existing.merchant_name = _candidate_merchant_name(match)
    existing.baseline_amount_cents = match.amount_cents
    existing.last_amount_cents = match.amount_cents
    existing.occurrence_count = _candidate_occurrence_count(payload, match, existing=existing)
    existing.last_seen_at = last_seen_at
    existing.next_expected_date = _candidate_next_expected_date(
        payload,
        last_seen_at=last_seen_at,
        timezone_name=timezone_name,
    )
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


def _create_recurring_item_from_candidate(
    db: Session,
    *,
    tenant_id: str,
    match: _RecurringCandidateMatch,
    payload: RecurringCandidateConfirmRequest,
    timezone_name: str | None,
) -> RecurringItem:
    last_seen_at = _candidate_last_seen_at(payload, match)
    confidence = _candidate_confidence(payload, match)
    now = now_utc()
    item = RecurringItem(
        tenant_id=tenant_id,
        merchant_key=match.merchant_key,
        merchant_name=_candidate_merchant_name(match),
        frequency=match.frequency,
        baseline_amount_cents=match.amount_cents,
        last_amount_cents=match.amount_cents,
        occurrence_count=_candidate_occurrence_count(payload, match),
        last_seen_at=last_seen_at,
        next_expected_date=_candidate_next_expected_date(
            payload,
            last_seen_at=last_seen_at,
            timezone_name=timezone_name,
        ),
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
            merchant_key=match.merchant_key,
            frequency=match.frequency,
        )
        if existing_after_race is not None:
            return existing_after_race
        raise
    db.refresh(item)
    return item


def _clean_frequency(value: str | None) -> str:
    frequency = (value or "monthly").strip()
    if frequency not in _VALID_FREQUENCIES:
        raise AppError("recurring_frequency_invalid", status_code=422)
    return frequency


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


def _candidate_merchant_name(match: _RecurringCandidateMatch) -> str:
    return str(match.candidate.get("merchant") or match.merchant)


def _candidate_last_seen_at(
    payload: RecurringCandidateConfirmRequest, match: _RecurringCandidateMatch
) -> datetime | None:
    return ensure_utc(payload.last_seen_at) or ensure_utc(match.candidate.get("last_seen_at"))


def _candidate_confidence(
    payload: RecurringCandidateConfirmRequest, match: _RecurringCandidateMatch
) -> object:
    return payload.confidence or match.candidate.get("confidence")


def _candidate_occurrence_count(
    payload: RecurringCandidateConfirmRequest,
    match: _RecurringCandidateMatch,
    *,
    existing: RecurringItem | None = None,
) -> int:
    counts = [
        int(payload.occurrence_count or 0),
        int(match.candidate.get("occurrence_count") or 0),
    ]
    if existing is not None:
        counts.append(int(existing.occurrence_count or 0))
    return max(counts)


def _candidate_next_expected_date(
    payload: RecurringCandidateConfirmRequest,
    *,
    last_seen_at: datetime | None,
    timezone_name: str | None,
) -> date | None:
    return payload.next_expected_date or _next_expected_date(last_seen_at, timezone_name)
