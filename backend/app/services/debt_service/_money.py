"""ADR-0049 §2.2 frozen-money resolution shared by Debt create + repayment.

A Debt principal (slice 1) and a repayment ``amount_cents`` (slice 2) both
freeze a backend-authoritative home-currency minor-units amount: a home-currency
amount is stored directly; a foreign-currency amount is converted from the
[[0027]] snapshot for its event/payment date and rejected with
``exchange_rate_pending`` (409) when the rate is not yet available — never
committing an un-foldable fact (§2.2). Original-currency fields are kept as
provenance/display only and MUST NOT be aggregated across currencies.

This is the single definition of that branch so ``_create`` (Debt principal) and
``_repayment`` (repayment payment) cannot drift. Clients never submit exchange
rates or compute home amounts.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.errors import AppError
from app.fx_constants import FX_STATUS_PENDING
from app.services.currency_common import home_currency_code, normalize_currency_code
from app.services.exchange_rate_service import (
    amount_major_to_minor,
    calculate_cny_cents,
    default_rate_date,
    resolve_payload_rate,
)


def freeze_home_amount(
    db: Session,
    *,
    tenant_id: str,
    amount_cents: int | None,
    original_currency: str | None,
    original_amount: Decimal | None,
    event_time: datetime | None,
    amount_error: str = "debt_amount_invalid",
) -> dict:
    """Resolve a frozen home amount + optional original-currency provenance.

    Home-currency path: ``amount_cents`` is the home amount (> 0), provenance
    fields stay NULL. Foreign-currency path: convert ``original_amount`` in
    ``original_currency`` to home minor units via the [[0027]] snapshot for the
    ``event_time`` accounting date and reject when the rate is pending (§2.2).
    The two inputs are mutually exclusive — mixing an explicit home amount with
    original-currency fields is rejected as ambiguous (``invalid_request``).

    Returns a dict whose keys match BOTH the Debt principal columns (when the
    caller renames ``amount_cents`` → ``principal_amount_cents``) and the
    Repayment columns: ``amount_cents`` / ``original_currency_code`` /
    ``original_amount_minor`` / ``exchange_rate_to_cny`` / ``exchange_rate_date``
    / ``exchange_rate_source``. ``home_currency_code`` is included too (the Debt
    principal stores it; the repayment caller drops it).
    """
    home = home_currency_code()
    has_original = original_currency is not None or original_amount is not None

    if not has_original:
        cents = _clean_home_amount(amount_cents, amount_error)
        return {
            "amount_cents": cents,
            "home_currency_code": home,
            "original_currency_code": None,
            "original_amount_minor": None,
            "exchange_rate_to_cny": None,
            "exchange_rate_date": None,
            "exchange_rate_source": None,
        }

    # Foreign-currency path: both original fields required, no client-supplied
    # home amount (the backend computes it).
    if original_currency is None or original_amount is None:
        raise AppError(amount_error, status_code=422)
    if amount_cents is not None:
        raise AppError("invalid_request", status_code=422)
    return _freeze_foreign_amount(
        db,
        tenant_id=tenant_id,
        home=home,
        original_currency=original_currency,
        original_amount=original_amount,
        event_time=event_time,
        amount_error=amount_error,
    )


def _freeze_foreign_amount(
    db: Session,
    *,
    tenant_id: str,
    home: str,
    original_currency: str,
    original_amount: Decimal,
    event_time: datetime | None,
    amount_error: str,
) -> dict:
    """Convert a foreign ``original_amount`` to home minor units via [[0027]]."""
    code = normalize_currency_code(original_currency)
    original_amount_minor = amount_major_to_minor(original_amount, code)
    if original_amount_minor is None or original_amount_minor <= 0:
        raise AppError(amount_error, status_code=422)
    rate_date = default_rate_date(event_time)

    if code == home:
        # Original currency IS home — no FX, store as a home amount but keep the
        # provenance the client asked for.
        rate: Decimal | None = Decimal("1")
        source: str | None = "base"
        fx_status = "ready"
        effective_date = rate_date
    else:
        rate, source, fx_status, effective_date = resolve_payload_rate(
            db,
            tenant_id=tenant_id,
            currency_code=code,
            rate_date=rate_date,
        )
    if fx_status == FX_STATUS_PENDING:
        # §2.2: cannot freeze a home amount yet — reject rather than commit an
        # un-foldable fact.
        raise AppError("exchange_rate_pending", status_code=409)

    cents = calculate_cny_cents(
        original_currency_code=code,
        original_amount_minor=original_amount_minor,
        exchange_rate_to_cny=rate,
    )
    if cents is None or cents <= 0:
        raise AppError(amount_error, status_code=422)
    return {
        "amount_cents": cents,
        "home_currency_code": home,
        "original_currency_code": code,
        "original_amount_minor": original_amount_minor,
        "exchange_rate_to_cny": rate,
        "exchange_rate_date": effective_date,
        "exchange_rate_source": source,
    }


def _clean_home_amount(value: int | None, amount_error: str) -> int:
    if value is None:
        raise AppError(amount_error, status_code=422)
    amount = int(value)
    if amount <= 0:
        raise AppError(amount_error, status_code=422)
    return amount
