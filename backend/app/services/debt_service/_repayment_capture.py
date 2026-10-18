"""Stage repayment notification evidence without invoking capture orchestration."""
import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.ledger_scope import ledger_scoped_select
from app.models import RepaymentDraft
from app.money_contract import MoneySign, ensure_money_minor
from app.schemas import RepaymentDraftCreateRequest
from app.services.currency_binding_service import assert_currency_binding_consistent, require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code
from app.services.debt_service._money import validate_home_amount_command
from app.services.debt_service._repayment_time import capture_repayment_time
from app.services.exchange_rate_service import amount_major_to_minor
from app.services.time_service import ensure_utc, now_utc

# Capture channels (display label is the /web source label, not the dedup axis).
# 花呗/借呗 surface from Alipay; 白条 from 京东/京东金融; 美团月付 from 美团; plus
# WeChat credit-card repayments and bank repayment SMS. Extendable as the Android
# package allowlist grows. The display strings mirror Android
# ``RepaymentDraftLabels.repaymentDraftSourceLabelRes`` / ``strings_stats_budget.xml``
# (§14 三端 copy 同步) — 平台带「还款」后缀, 短信/App 渠道不带; keys are the api ``source``
# values (``_clean_repayment_source`` validates against this key set).
REPAYMENT_DRAFT_SOURCE_LABELS = {
    "alipay": "支付宝还款",
    "jd": "京东还款",
    "meituan": "美团还款",
    "wechat": "微信还款",
    "bank_sms": "银行短信",
    "bank_app": "银行 App",
    "other": "其他还款",
}

_REPAYMENT_DRAFT_WINDOW_MINUTES = 30


def _clean_repayment_source(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_")
    if cleaned not in REPAYMENT_DRAFT_SOURCE_LABELS:
        raise AppError("notification_source_invalid", status_code=422)
    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _repayment_window_key(captured_at) -> str:
    when = ensure_utc(captured_at)
    minute = (when.minute // _REPAYMENT_DRAFT_WINDOW_MINUTES) * _REPAYMENT_DRAFT_WINDOW_MINUTES
    bucket = when.replace(minute=minute, second=0, microsecond=0)
    return bucket.isoformat()


def _repayment_draft_key(
    *,
    source: str,
    merchant: str | None,
    amount_cents: int,
    home_currency: str,
    captured_at,
    notification_key: str | None = None,
) -> str:
    # ``notification_key`` is the Android per-post identity (SHA-256(sbn.key|postTime)) —
    # the PRIMARY dedup axis (codex PR#20). Distinct posts → distinct drafts; the same
    # post re-sent → dedupe. Absent → "" reduces the key to content+window. The
    # "repayment_notification" prefix keeps this namespace disjoint from the expense
    # ``_notification_draft_key`` ("notification"), so a repayment and a same-amount
    # expense never collide.
    merchant_key = (merchant or "").strip()
    material = "|".join(
        [
            "repayment_notification",
            (notification_key or "").strip(),
            source,
            merchant_key.casefold(),
            str(amount_cents),
            (home_currency or "").strip().upper(),
            _repayment_window_key(captured_at),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def stage_repayment_draft(
    db: Session,
    *,
    payload: RepaymentDraftCreateRequest,
    tenant_id: str,
    actor_account_id: int,
) -> RepaymentDraft:
    """Capture one pending repayment draft, deduped per account (ADR-0049 §杠杆③).

    A re-posted notification (same identity/content/window) returns the ACTOR'S OWN
    existing draft rather than inserting a twin — same content-dedup contract as the
    expense notification-draft path, including the IntegrityError race fallback. The
    idempotency domain is (tenant, created_by_account_id, key) (issue #224 / C3): both
    the first-check and the race re-check filter ``created_by_account_id`` so a
    co-member's same-key capture is neither returned (leak) nor collided with.
    """
    validate_home_amount_command(amount_cents=payload.amount_cents,
        original_currency=payload.original_currency, original_amount=payload.original_amount)
    original_currency = normalize_currency_code(payload.original_currency or DEFAULT_HOME_CURRENCY_CODE)
    original_amount = ensure_money_minor(
        amount_major_to_minor(payload.original_amount, original_currency)
        if payload.original_currency is not None else payload.amount_cents,
        sign=MoneySign.POSITIVE,
        label="repayment_draft.original_amount_minor",
    )
    now = now_utc()
    source = _clean_repayment_source(payload.source)
    # Capture retains the original; only explicit human confirmation freezes FX.
    home_currency = require_runtime_home_currency_code(db)
    assert_currency_binding_consistent(db, home_currency)
    amount_cents = original_amount if original_currency == home_currency else None
    captured_at = ensure_utc(payload.captured_at) if payload.captured_at else now
    idempotency_key = _repayment_draft_key(
        source=source,
        merchant=payload.merchant_label,
        amount_cents=original_amount,
        home_currency=original_currency,
        captured_at=captured_at,
        notification_key=payload.notification_key,
    )
    existing = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id)
        .where(RepaymentDraft.created_by_account_id == actor_account_id)
        .where(RepaymentDraft.draft_idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing

    payment_time = capture_repayment_time(db, ledger_id=tenant_id, captured_at=payload.captured_at or captured_at)
    draft = RepaymentDraft(
        tenant_id=tenant_id,
        created_by_account_id=actor_account_id,
        source=source,
        amount_cents=amount_cents,
        home_currency_code=home_currency,
        original_currency_code=original_currency,
        original_amount_minor=original_amount,
        merchant_label=_clean_optional_text(payload.merchant_label),
        captured_at=captured_at,
        accounting_time_snapshot=payment_time.model_dump(mode="json"),
        draft_idempotency_key=idempotency_key,
        status="pending",
        created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(draft)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            ledger_scoped_select(RepaymentDraft, tenant_id)
            .where(RepaymentDraft.created_by_account_id == actor_account_id)
            .where(RepaymentDraft.draft_idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        raise
    return draft
