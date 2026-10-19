"""Native amounts are authoritative; home values retain their transaction-date snapshot."""
from app.errors import AppError
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.exchange_rate_service import calculate_cny_cents, resolve_payload_rate


def home_value(db, *, ledger_id, currency, amount_minor, occurred_on, required=False):
    return valuation(db, ledger_id=ledger_id, currency=currency, amount_minor=amount_minor,
        occurred_on=occurred_on, required=required)[0]


def valuation(db, *, ledger_id, currency, amount_minor, occurred_on, required=False):
    home = require_runtime_home_currency_code(db)
    rate, source, status, effective_date = resolve_payload_rate(db, tenant_id=ledger_id, currency_code=currency,
        home_currency_code=home, rate_date=occurred_on)
    snapshot = {"currency_code": currency, "home_currency_code": home, "rate": str(rate) if rate is not None else None,
        "source": source, "status": status, "rate_date": effective_date.isoformat(), "transaction_date": occurred_on.isoformat()}
    if amount_minor == 0:
        return 0, snapshot
    if rate is None:
        if required:
            raise AppError("exchange_rate_pending", "原币金额已保留，请补齐交易日汇率后继续。", status_code=409)
        return None, snapshot
    return calculate_cny_cents(home_currency_code=home, original_currency_code=currency, original_amount_minor=abs(amount_minor), exchange_rate_to_cny=rate) * (1 if amount_minor > 0 else -1), snapshot
