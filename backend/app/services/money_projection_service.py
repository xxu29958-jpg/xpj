"""Read-only conversion of captured money through the existing FX owner."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.money_contract import projection_values_sum_to_int
from app.services.category_service import normalize_category
from app.services.exchange_rate_service import calculate_cny_cents, resolve_payload_rate


@dataclass(frozen=True)
class CategorySpend:
    amount_cents: int | None = 0
    count: int = 0


def sum_projected_amounts(values, *, label: str) -> int | None:
    amounts = list(values)
    if any(amount is None for amount in amounts):
        return None
    return projection_values_sum_to_int(amounts, label=label)


def project_category_spend(db: Session, *, tenant_id: str, home: str, rows) -> tuple[dict[str, CategorySpend], set[str]]:
    spend: dict[str, CategorySpend] = {}
    missing: set[str] = set()
    for row in rows:
        category = normalize_category(row.category)
        current = spend.get(category, CategorySpend())
        amount = project_recorded_amount(db, tenant_id=tenant_id, amount_minor=row.amount_cents,
            source_currency=row.home_currency_code, home_currency=home, rate_date=row.stream_date)
        if amount is None:
            missing.add(row.home_currency_code or "UNKNOWN")
        spend[category] = CategorySpend(
            amount_cents=sum_projected_amounts((current.amount_cents, amount), label="spending.category_total"),
            count=current.count + 1,
        )
    return spend, missing


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
