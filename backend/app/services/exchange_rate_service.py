from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import (
    DEFAULT_HOME_CURRENCY_CODE,
    DEFAULT_SUPPORTED_CURRENCY_CODES,
    FX_SOURCE_BASE,
    FX_SOURCE_MANUAL,
    FX_STATUS_PENDING,
    FX_STATUS_READY,
)
from app.ledger_scope import ledger_scoped_select
from app.models import ExchangeRate, Expense
from app.money_contract import (
    MoneySign,
    ensure_optional_money_minor,
)
from app.schemas._exchange import ExchangeRateRequest, ExchangeRateResponse
from app.services.currency_binding_service import (
    require_runtime_home_currency_code,
    resolve_write_capability,
)
from app.services.currency_common import (
    RATE_QUANT,
    format_decimal_rate,
    major_amount_to_minor,
    minor_unit_digits,
    normalize_currency_code,
    supported_currency_codes,
)
from app.services.fx_rate_provider import get_covered_fx_rate, get_fx_rate_on_or_before
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.spending_contract_service import fx_rate_date_for_expense_time
from app.services.time_service import now_utc

BASE_CURRENCY_CODE = DEFAULT_HOME_CURRENCY_CODE
HOME_CURRENCY_CODE = DEFAULT_HOME_CURRENCY_CODE
SUPPORTED_CURRENCY_CODES = set(DEFAULT_SUPPORTED_CURRENCY_CODES)

# Re-exports — existing callers do ``from app.services.exchange_rate_service
# import normalization/arithmetic helpers. Money authority stays with the binding.
__all_currency_helpers = (
    RATE_QUANT,
    format_decimal_rate,
    normalize_currency_code,
    supported_currency_codes,
)


class CurrencyPayload(Protocol):
    amount_cents: int | None
    original_currency: str | None
    original_amount: Decimal | None
    spent_at: datetime | None
    original_currency_code: str | None
    original_amount_minor: int | None
    exchange_rate_to_cny: Decimal | None
    exchange_rate_date: date | None
    exchange_rate_source: str | None


def validate_currency_payload_money_command(
    payload: CurrencyPayload,
    *,
    amount_was_explicit: bool,
) -> None:
    """Validate direct carriers before a currency write can touch the DB."""

    amount_cents = _payload_attr(payload, "amount_cents")
    if amount_was_explicit or amount_cents is not None:
        ensure_optional_money_minor(
            amount_cents,
            sign=MoneySign.NONNEGATIVE,
            label="expense.amount_cents",
        )
    ensure_optional_money_minor(
        _payload_attr(payload, "original_amount_minor"),
        sign=MoneySign.NONNEGATIVE,
        label="expense.original_amount_minor",
    )
    original_amount = _payload_attr(payload, "original_amount")
    explicit_code = _payload_attr(
        payload,
        "original_currency",
    ) or _payload_attr(payload, "original_currency_code")
    if original_amount is not None and explicit_code is not None:
        amount_major_to_minor(original_amount, explicit_code)


def minor_units_for_currency(currency_code: str) -> int:
    return minor_unit_digits(normalize_currency_code(currency_code))


def amount_major_to_minor(value: Decimal | None, currency_code: str) -> int | None:
    return major_amount_to_minor(value, normalize_currency_code(currency_code))


def calculate_cny_cents(
    *,
    home_currency_code: str,
    original_currency_code: str,
    original_amount_minor: int | None,
    exchange_rate_to_cny: Decimal | None,
) -> int | None:
    """Convert original currency minor units → home currency minor units.

    The legacy name says "cny_cents" but the result is always expressed in the
    supplied home currency's minor units. If the persisted home currency is a
    no-fraction currency (JPY/KRW), the multiplier collapses to 1 so that 1,000
    JPY persists as `amount_cents=1000` rather than 100,000.
    """
    if original_amount_minor is None:
        return None
    original_minor = ensure_optional_money_minor(
        original_amount_minor,
        sign=MoneySign.NONNEGATIVE,
        label="expense.original_amount_minor",
    )
    assert original_minor is not None
    currency_code = normalize_currency_code(original_currency_code)
    home = normalize_currency_code(home_currency_code)
    rate = Decimal("1") if currency_code == home else format_decimal_rate(exchange_rate_to_cny)
    if rate is None:
        return None
    divisor = Decimal(10) ** minor_units_for_currency(currency_code)
    amount_major = Decimal(original_minor) / divisor
    home_units = minor_units_for_currency(home)
    home_multiplier = Decimal(10) ** home_units
    home_minor = int(
        (amount_major * rate * home_multiplier).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
    return ensure_optional_money_minor(
        home_minor,
        sign=MoneySign.NONNEGATIVE,
        label="expense.amount_cents.fx_result",
    )


def default_rate_date(expense_time: datetime | None = None) -> date:
    return fx_rate_date_for_expense_time(expense_time)


def _payload_rate_date(payload: CurrencyPayload, expense_time: datetime | None) -> date:
    payload_time = _payload_attr(payload, "spent_at") or _payload_attr(payload, "expense_time")
    return default_rate_date(payload_time or expense_time)


def get_exchange_rate(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str,
    rate_date: date,
    home_currency_code: str,
) -> ExchangeRate | None:
    code = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code)
    if code == home:
        return None
    return db.scalar(
        ledger_scoped_select(ExchangeRate, tenant_id)
        .where(ExchangeRate.home_currency_code == home)
        .where(ExchangeRate.currency_code == code)
        .where(ExchangeRate.rate_date == rate_date)
    )


def list_exchange_rates(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str | None = None,
    home_currency_code: str | None = None,
    rate_date: date | None = None,
    limit: int = 90,
) -> list[ExchangeRate]:
    require_runtime_home_currency_code(db)
    query = ledger_scoped_select(ExchangeRate, tenant_id)
    if home_currency_code:
        query = query.where(ExchangeRate.home_currency_code == normalize_currency_code(home_currency_code))
    if currency_code:
        query = query.where(ExchangeRate.currency_code == normalize_currency_code(currency_code))
    if rate_date is not None:
        query = query.where(ExchangeRate.rate_date == rate_date)
    return list(
        db.scalars(
            query.order_by(ExchangeRate.rate_date.desc(), ExchangeRate.currency_code.asc(), ExchangeRate.home_currency_code.asc())
            .limit(min(max(limit, 1), 365))
        )
    )


def _manual_rate_intent(payload: ExchangeRateRequest) -> ExchangeRateRequest:
    code = normalize_currency_code(payload.currency_code)
    home = normalize_currency_code(payload.home_currency_code)
    if code == home:
        raise AppError("exchange_rate_base_currency", status_code=422)
    return payload.model_copy(update={"currency_code": code, "home_currency_code": home,
        "rate_to_cny": format_decimal_rate(payload.rate_to_cny),
        "source": (payload.source or FX_SOURCE_MANUAL).strip() or FX_SOURCE_MANUAL})


def _original_rate_receipt(claim, payload: ExchangeRateRequest) -> ExchangeRateResponse:
    try:
        result = ExchangeRateResponse.model_validate(claim.row.response_body)
        fields = ("currency_code", "home_currency_code", "rate_date", "rate_to_cny", "source")
        if result.public_id != claim.row.resource_id or result.row_version != payload.expected_row_version + 1 or any(
            getattr(result, field) != getattr(payload, field) for field in fields
        ):
            raise ValueError("Original rate response does not match its intent")
        return result
    except (ValidationError, ValueError) as exc:
        raise AppError("exchange_rate_response_unverified", "原汇率提交缺少可核对的回执，请保留原输入并核对汇率。",
            status_code=409) from exc


def _write_manual_rate(db: Session, *, tenant_id: str, payload: ExchangeRateRequest) -> ExchangeRate:
    """Create once or correct exactly the version the user reviewed."""
    resolve_write_capability(db)
    values = payload.model_dump(exclude={"expected_row_version"})
    now = now_utc()
    if payload.expected_row_version == 0:
        statement = insert(ExchangeRate).values(**values, tenant_id=tenant_id,
            created_at=now, updated_at=now, row_version=1).on_conflict_do_nothing(
                constraint="uq_exchange_rates_tenant_pair_date")
    else:
        statement = update(ExchangeRate).where(
            ExchangeRate.tenant_id == tenant_id,
            ExchangeRate.currency_code == payload.currency_code,
            ExchangeRate.home_currency_code == payload.home_currency_code,
            ExchangeRate.rate_date == payload.rate_date,
            ExchangeRate.row_version == payload.expected_row_version,
        ).values(rate_to_cny=payload.rate_to_cny, source=payload.source,
            updated_at=now, row_version=ExchangeRate.row_version + 1)
    result = db.scalar(statement.returning(ExchangeRate).execution_options(populate_existing=True))
    if result is None:
        raise AppError("state_conflict", "这项人工汇率已变化，请保留原输入并核对当前汇率后再纠正。", status_code=409)
    return result


def set_exchange_rate_idempotently(
    db: Session, *, tenant_id: str, actor_account_id: int | None,
    payload: ExchangeRateRequest, idempotency_key: str | None,
) -> ExchangeRateResponse:
    """One transaction owns the rate and the original accepted response."""
    if not idempotency_key or not idempotency_key.strip():
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    intent = _manual_rate_intent(payload)
    target = f"{intent.currency_code}:{intent.home_currency_code}:{intent.rate_date.isoformat()}"
    claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation="set_exchange_rate", target_type="exchange_rate", target_id=target,
        request_fingerprint=fingerprint_request(operation="set_exchange_rate", target_id=target,
            body={"actor_account_id": actor_account_id, "intent": intent.model_dump(mode="json",
                exclude={"expected_row_version"})}, expected_row_version=intent.expected_row_version))
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    if claim.kind is IdempotencyOutcomeKind.HIT:
        return _original_rate_receipt(claim, intent)
    row = _write_manual_rate(db, tenant_id=tenant_id, payload=intent)
    result = ExchangeRateResponse.model_validate(row)
    mark_idempotency_succeeded(db, claim.row, resource_type="exchange_rate", resource_id=result.public_id,
        response_body=result.model_dump(mode="json"))
    db.commit()
    return result


def resolve_payload_rate(
    db: Session,
    *,
    tenant_id: str,
    currency_code: str,
    home_currency_code: str,
    rate_date: date,
) -> tuple[Decimal | None, str | None, str, date]:
    """Resolve (rate, source, fx_status, effective_date) for a currency on a date.

    ``effective_date`` is the date the returned rate was actually published — for
    the weekend / holiday fallback it is the earlier working-day row's date, NOT
    the requested ``rate_date``. The caller freezes it into the snapshot so the
    record is honest about provenance (ADR-0027: the snapshot must not claim a
    rate "as of" a date the source never published). On ``pending`` there is no
    rate, so the requested date is echoed back.
    """
    code = normalize_currency_code(currency_code)
    home = normalize_currency_code(home_currency_code)
    if code == home:
        return Decimal("1"), FX_SOURCE_BASE, FX_STATUS_READY, rate_date
    stored = get_exchange_rate(
        db,
        tenant_id=tenant_id,
        currency_code=code,
        rate_date=rate_date,
        home_currency_code=home,
    )
    if stored is not None:
        return Decimal(stored.rate_to_cny), stored.source, FX_STATUS_READY, stored.rate_date
    # A published row proves its own day. An earlier row needs evidence that
    # the requested day was checked, including weekends and holidays.
    global_rate = get_covered_fx_rate(
        db,
        currency_code=code,
        rate_date=rate_date,
        home_currency_code=home,
    )
    if global_rate is not None:
        return Decimal(global_rate.rate_to_home), global_rate.source, FX_STATUS_READY, global_rate.rate_date
    return None, None, FX_STATUS_PENDING, rate_date


def resolve_valuation_rate(
    db: Session, *, tenant_id: str, currency_code: str, home_currency_code: str, rate_date: date,
) -> tuple[Decimal | None, str | None, str, date]:
    """Value a current plan from the latest known quote, retaining its real date."""
    resolved = resolve_payload_rate(db, tenant_id=tenant_id, currency_code=currency_code,
        home_currency_code=home_currency_code, rate_date=rate_date)
    if resolved[0] is not None:
        return resolved
    row = get_fx_rate_on_or_before(db, currency_code=currency_code,
        home_currency_code=home_currency_code, rate_date=rate_date)
    if row is None:
        return resolved
    return Decimal(row.rate_to_home), row.source, FX_STATUS_READY, row.rate_date


def _payload_attr(payload: CurrencyPayload, name: str):
    return getattr(payload, name, None)


def _payload_original_currency(payload: CurrencyPayload, expense: Expense, *, home: str) -> str:
    return normalize_currency_code(
        _payload_attr(payload, "original_currency")
        or _payload_attr(payload, "original_currency_code")
        or expense.original_currency_code
        or home
    )


def _payload_original_amount_minor(
    payload: CurrencyPayload,
    *,
    currency_code: str,
    home: str,
    amount_was_explicit: bool,
) -> int | None:
    original_amount = amount_major_to_minor(_payload_attr(payload, "original_amount"), currency_code)
    if original_amount is not None:
        return original_amount
    original_amount_minor = _payload_attr(payload, "original_amount_minor")
    if original_amount_minor is not None:
        return ensure_optional_money_minor(
            original_amount_minor,
            sign=MoneySign.NONNEGATIVE,
            label="expense.original_amount_minor",
        )
    amount_cents = _payload_attr(payload, "amount_cents")
    if amount_was_explicit and amount_cents is not None and currency_code == home:
        return ensure_optional_money_minor(
            amount_cents,
            sign=MoneySign.NONNEGATIVE,
            label="expense.amount_cents",
        )
    return None


def _currency_payload_has_original_fields(payload: CurrencyPayload) -> bool:
    return any(
        value is not None
        for value in (
            _payload_attr(payload, "original_currency"),
            _payload_attr(payload, "original_amount"),
            _payload_attr(payload, "spent_at"),
            _payload_attr(payload, "expense_time"),
            _payload_attr(payload, "original_currency_code"),
            _payload_attr(payload, "original_amount_minor"),
            _payload_attr(payload, "exchange_rate_to_cny"),
            _payload_attr(payload, "exchange_rate_date"),
        )
    )


def _apply_legacy_home_amount(
    expense: Expense,
    payload: CurrencyPayload,
    *,
    home: str,
) -> None:
    amount_cents = _payload_attr(payload, "amount_cents")
    expense.amount_cents = amount_cents
    expense.home_currency_code = home
    expense.original_currency_code = home
    expense.original_amount_minor = amount_cents
    expense.exchange_rate_to_cny = Decimal("1") if amount_cents is not None else None
    expense.exchange_rate_date = default_rate_date(expense.expense_time) if amount_cents is not None else None
    expense.exchange_rate_source = FX_SOURCE_BASE if amount_cents is not None else None
    expense.fx_status = FX_STATUS_READY


def apply_currency_payload(
    db: Session,
    *,
    tenant_id: str,
    home_currency_code: str,
    expense: Expense,
    payload: CurrencyPayload,
    amount_was_explicit: bool,
    manual_exchange_rate: Decimal | None = None,
) -> None:
    validate_currency_payload_money_command(
        payload,
        amount_was_explicit=amount_was_explicit,
    )
    has_original_fields = _currency_payload_has_original_fields(payload) or manual_exchange_rate is not None
    if not has_original_fields and not amount_was_explicit:
        # R10②：纯元数据维护不读 env、不过门（不碰币种快照，漂移/配错 env 不拖死它）。
        return
    home = normalize_currency_code(home_currency_code)
    resolve_write_capability(db)
    if not has_original_fields:
        _apply_legacy_home_amount(expense, payload, home=home)
        return

    code = _payload_original_currency(payload, expense, home=home)
    original_amount = _payload_original_amount_minor(
        payload,
        currency_code=code,
        home=home,
        amount_was_explicit=amount_was_explicit,
    )
    if original_amount is None:
        original_amount = expense.original_amount_minor
    explicit_rate_date = _payload_attr(payload, "exchange_rate_date")
    time_changed = _payload_attr(payload, "spent_at") is not None or _payload_attr(payload, "expense_time") is not None
    rate_date = (
        explicit_rate_date
        or (_payload_rate_date(payload, expense.expense_time) if time_changed else None)
        or expense.exchange_rate_date
        or _payload_rate_date(payload, expense.expense_time)
    )
    if manual_exchange_rate is not None:
        if code == home:
            raise AppError("exchange_rate_base_currency", status_code=422)
        rate = format_decimal_rate(manual_exchange_rate)
        source, fx_status = FX_SOURCE_MANUAL, FX_STATUS_READY
        effective_rate_date = _payload_rate_date(payload, expense.expense_time)
    elif code == home:
        rate, source, fx_status, effective_rate_date = Decimal("1"), FX_SOURCE_BASE, FX_STATUS_READY, rate_date
    else:
        rate, source, fx_status, effective_rate_date = resolve_payload_rate(
            db,
            tenant_id=tenant_id,
            home_currency_code=home,
            currency_code=code,
            rate_date=rate_date,
        )
    expense.home_currency_code = home
    expense.original_currency_code = code
    expense.original_amount_minor = original_amount
    apply_resolved_currency_rate(expense, rate=rate, source=source,
        fx_status=fx_status, rate_date=effective_rate_date)


def apply_resolved_currency_rate(
    expense: Expense, *, rate: Decimal | None, source: str | None, fx_status: str, rate_date: date,
) -> None:
    """Apply an already resolved reference without changing original money or confirming."""
    expense.exchange_rate_to_cny = rate
    expense.exchange_rate_date = rate_date
    expense.exchange_rate_source = source
    expense.fx_status = fx_status
    expense.amount_cents = calculate_cny_cents(
        home_currency_code=expense.home_currency_code,
        original_currency_code=expense.original_currency_code,
        original_amount_minor=expense.original_amount_minor,
        exchange_rate_to_cny=rate,
    )
