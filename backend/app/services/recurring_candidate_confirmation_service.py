from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import ApiIdempotencyKey, RecurringItem
from app.money_contract import (
    MoneySign,
    ensure_money_minor,
    projection_sum_to_int,
)
from app.schemas import RecurringCandidateConfirmRequest, RecurringItemResponse
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_common import normalize_currency_code
from app.services.idempotency import claim_idempotency_key, fingerprint_request
from app.services.insights_service import recurring_candidates
from app.services.merchant_service import normalize_merchant
from app.services.recurring_history_service import record_recurring_item_revision
from app.services.recurring_item_command_service import (
    publish_recurring_receipt,
    raise_recurring_item_conflict,
    replay_recurring_receipt,
)
from app.services.recurring_merchant_capacity import ensure_recurring_merchant_storage_shape
from app.services.time_service import ensure_utc, now_utc, safe_zone

_VALID_FREQUENCIES = {"monthly"}


@dataclass(frozen=True)
class _RecurringCandidateMatch:
    merchant: str
    merchant_key: str
    frequency: str
    amount_cents: int
    home_currency_code: str
    candidate: dict


CONFIRM_RECURRING_CANDIDATE_OPERATION = "confirm_recurring_candidate"


def confirm_recurring_candidate(
    db: Session,
    *,
    tenant_id: str,
    payload: RecurringCandidateConfirmRequest,
    idempotency_key: str | None = None,
    timezone_name: str | None = None,
    actor_account_id: int | None = None,
) -> RecurringItemResponse:
    """Adopt a current observation once, retaining the first accepted definition."""
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    merchant_key, frequency, amount_cents = _validated_candidate_intent(payload)
    home = normalize_currency_code(payload.home_currency_code)
    body = {"merchant": payload.merchant, "frequency": frequency, "amount_cents": amount_cents,
        "home_currency_code": home, "timezone": timezone_name}
    if "next_expected_date" in payload.model_fields_set:
        body["next_expected_date"] = payload.next_expected_date.isoformat() if payload.next_expected_date else None
    outcome = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation=CONFIRM_RECURRING_CANDIDATE_OPERATION, target_type="recurring_item",
        request_fingerprint=fingerprint_request(operation=CONFIRM_RECURRING_CANDIDATE_OPERATION,
            target_id=None, body=body, expected_row_version=None))
    replayed = replay_recurring_receipt(outcome)
    if replayed is not None:
        return replayed
    existing = _existing_item(db, tenant_id=tenant_id, merchant_key=merchant_key, frequency=frequency)
    if existing is not None:
        if existing.status == "archived":
            raise AppError("recurring_item_archived", status_code=409,
                details={"public_id": existing.public_id, "status": existing.status})
        raise_recurring_item_conflict(existing)
    match = _require_recurring_candidate_match(db, tenant_id=tenant_id, payload=payload,
        timezone_name=timezone_name)
    return _create_recurring_item_from_candidate(db, tenant_id=tenant_id, match=match, payload=payload,
        claim=outcome.row, timezone_name=timezone_name, actor_account_id=actor_account_id)


def _validated_candidate_intent(payload: RecurringCandidateConfirmRequest) -> tuple[str, str, int]:
    merchant_name = payload.merchant.strip()
    merchant_key = normalize_merchant(merchant_name)
    ensure_recurring_merchant_storage_shape(merchant_name=merchant_name, merchant_key=merchant_key)
    frequency = _clean_frequency(payload.frequency)
    amount_cents = ensure_money_minor(
        payload.amount_cents,
        sign=MoneySign.POSITIVE,
        label="recurring_candidate.amount_cents",
    )
    return merchant_key, frequency, amount_cents


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

    amount_cents = ensure_money_minor(
        payload.amount_cents,
        sign=MoneySign.POSITIVE,
        label="recurring_candidate.amount_cents",
    )
    candidate = _find_recurring_candidate(
        db,
        tenant_id=tenant_id,
        merchant_key=merchant_key,
        amount_cents=amount_cents,
        home_currency_code=normalize_currency_code(payload.home_currency_code),
        timezone_name=timezone_name,
    )
    if candidate is None:
        raise AppError("recurring_candidate_not_found", status_code=404)

    return _RecurringCandidateMatch(
        merchant=merchant,
        merchant_key=merchant_key,
        frequency=_clean_frequency(payload.frequency),
        amount_cents=amount_cents,
        home_currency_code=normalize_currency_code(payload.home_currency_code),
        candidate=candidate,
    )


def _create_recurring_item_from_candidate(
    db: Session,
    *,
    tenant_id: str,
    match: _RecurringCandidateMatch,
    payload: RecurringCandidateConfirmRequest,
    claim: ApiIdempotencyKey,
    timezone_name: str | None,
    actor_account_id: int | None = None,
) -> RecurringItemResponse:
    # Observation provenance belongs to the server-side candidate scan. The
    # request still carries legacy fields for wire compatibility, but a Web or
    # Android consumer must not be able to manufacture a larger occurrence
    # count, a newer observation timestamp, or a stronger/weaker confidence.
    last_seen_at = _candidate_last_seen_at(match)
    confidence = _candidate_confidence(match)
    now = now_utc()
    # R15b-4：RecurringItem 属门证据集的无绑定表 —— 创建前过 ADR-0075 写门
    # （与 R13-2 五入口同模式；drift 窗口不得写入新无绑定行）。
    resolve_write_capability(db)
    item = RecurringItem(
        tenant_id=tenant_id,
        merchant_key=match.merchant_key,
        merchant_name=_candidate_merchant_name(match),
        home_currency_code=match.home_currency_code,
        frequency=match.frequency,
        baseline_amount_cents=match.amount_cents,
        last_amount_cents=match.amount_cents,
        occurrence_count=_candidate_occurrence_count(match),
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
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        raced = _existing_item(db, tenant_id=tenant_id, merchant_key=match.merchant_key, frequency=match.frequency)
        if raced is not None:
            raise_recurring_item_conflict(raced)
        raise
    record_recurring_item_revision(db, item, change_kind="create", actor_account_id=actor_account_id)
    return publish_recurring_receipt(db, claim, item)


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
    home_currency_code: str,
    timezone_name: str | None,
) -> dict | None:
    for item in recurring_candidates(db, tenant_id=tenant_id, timezone_name=timezone_name, home_currency_code=home_currency_code):
        if normalize_merchant(item.get("merchant")) != merchant_key:
            continue
        if (
            projection_sum_to_int(
                item.get("amount_cents"),
                label="recurring_candidate.match_amount",
            )
            != amount_cents
        ):
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


def _candidate_last_seen_at(match: _RecurringCandidateMatch) -> datetime | None:
    return ensure_utc(match.candidate.get("last_seen_at"))


def _candidate_confidence(match: _RecurringCandidateMatch) -> object:
    return match.candidate.get("confidence")


def _candidate_occurrence_count(match: _RecurringCandidateMatch) -> int:
    return int(match.candidate.get("occurrence_count") or 0)


def _candidate_next_expected_date(
    payload: RecurringCandidateConfirmRequest,
    *,
    last_seen_at: datetime | None,
    timezone_name: str | None,
) -> date | None:
    if "next_expected_date" in payload.model_fields_set:
        return payload.next_expected_date
    return _next_expected_date(last_seen_at, timezone_name)
