"""Read-only conversion of captured money through the existing FX owner."""

from datetime import date

from sqlalchemy.orm import Session

from app.services.exchange_rate_service import calculate_cny_cents, resolve_payload_rate


def project_recorded_amount(
    db: Session, *, tenant_id: str, amount_minor: int, source_currency: str | None,
    home_currency: str | None, rate_date: date,
) -> int | None:
    if source_currency is None or home_currency is None:
        return None
    if source_currency == home_currency or amount_minor == 0:
        return amount_minor
    rate, _, _, _ = resolve_payload_rate(
        db, tenant_id=tenant_id, currency_code=source_currency,
        home_currency_code=home_currency, rate_date=rate_date,
    )
    converted = calculate_cny_cents(
        home_currency_code=home_currency, original_currency_code=source_currency,
        original_amount_minor=abs(amount_minor), exchange_rate_to_cny=rate,
    )
    if converted is None:
        return None
    return -converted if amount_minor < 0 else converted
