"""The real global FX cache keeps valuation and historical coverage distinct."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import FxRate
from app.services import fx_rate_provider as provider


def test_legacy_quote_is_currently_readable_but_cannot_prove_a_later_historical_day():
    friday, sunday = date(2026, 5, 29), date(2026, 5, 31)
    with SessionLocal() as db:
        quote = provider.upsert_fx_rate(
            db, currency_code="USD", rate_date=friday, home_currency_code="CNY", rate_to_home=Decimal("7"),
        )
        assert quote.verified_through is None
        pair = {"currency_code": "USD", "home_currency_code": "CNY"}
        assert provider.get_covered_fx_rate(db, rate_date=friday, **pair).id == quote.id
        assert provider.get_fx_rate_on_or_before(db, rate_date=sunday, **pair).id == quote.id
        assert provider.get_covered_fx_rate(db, rate_date=sunday, **pair) is None
        assert provider.get_covered_fx_rate(db, rate_date=date(2026, 5, 28), **pair) is None


def test_dated_cache_preserves_publication_and_monotonically_merges_coverage(monkeypatch):
    monkeypatch.setattr(provider, "now_utc", lambda: datetime(2026, 6, 2, 12, tzinfo=UTC))
    friday, sunday = date(2026, 5, 29), date(2026, 5, 31)
    daily = provider.EcbDailyRates(friday, {"EUR": Decimal("1"), "USD": Decimal("1"), "CNY": Decimal("7")})
    with SessionLocal() as db:
        first = provider.cache_reference_rates_for_date(
            db, daily, requested_date=sunday, home_currency_code="CNY", currencies={"USD"},
        )[0]
        original_id = first.id
        for requested in (friday, date(2026, 6, 2)):
            quote = provider.cache_reference_rates_for_date(
                db, daily, requested_date=requested, home_currency_code="CNY", currencies={"USD"},
            )[0]
            assert (quote.id, quote.rate_date, quote.verified_through) == (original_id, friday, sunday)
        latest = provider.upsert_fx_rate(
            db, currency_code="USD", rate_date=friday, home_currency_code="CNY", rate_to_home=Decimal("7.1"),
        )
        assert (latest.id, latest.verified_through) == (original_id, sunday)
        assert latest.rate_to_home == Decimal("7.1")
        covered = provider.get_covered_fx_rate(db, currency_code="USD", rate_date=sunday, home_currency_code="CNY")
        assert covered.id == original_id
        assert provider.get_covered_fx_rate(db, currency_code="USD", rate_date=sunday, home_currency_code="JPY") is None
        assert len(db.scalars(select(FxRate)).all()) == 1


def test_today_quote_is_available_to_its_caller_without_permanent_today_coverage(monkeypatch):
    monday = date(2026, 6, 1)
    monkeypatch.setattr(provider, "now_utc", lambda: datetime(2026, 6, 1, 6, tzinfo=UTC))
    daily = provider.EcbDailyRates(date(2026, 5, 29), {"EUR": Decimal("1"), "USD": Decimal("1"), "CNY": Decimal("7")})
    with SessionLocal() as db:
        quote = provider.cache_reference_rates_for_date(
            db, daily, requested_date=monday, home_currency_code="CNY", currencies={"USD"},
        )[0]
        assert quote.rate_to_home == Decimal("7")
        assert quote.verified_through is None
        assert provider.get_covered_fx_rate(db, currency_code="USD", rate_date=monday, home_currency_code="CNY") is None
        monkeypatch.setattr(provider, "now_utc", lambda: datetime(2026, 6, 2, 6, tzinfo=UTC))
        assert provider.get_covered_fx_rate(db, currency_code="USD", rate_date=monday, home_currency_code="CNY") is None


def test_an_older_covered_quote_cannot_hide_a_newer_known_publication(monkeypatch):
    monkeypatch.setattr(provider, "now_utc", lambda: datetime(2026, 6, 2, 12, tzinfo=UTC))
    sunday = date(2026, 5, 31)
    with SessionLocal() as db:
        provider.upsert_fx_rate(
            db, currency_code="USD", rate_date=date(2026, 5, 28), home_currency_code="CNY",
            rate_to_home=Decimal("7"), verified_through=sunday,
        )
        provider.upsert_fx_rate(
            db, currency_code="USD", rate_date=date(2026, 5, 29), home_currency_code="CNY",
            rate_to_home=Decimal("7.1"),
        )
        assert provider.get_covered_fx_rate(db, currency_code="USD", rate_date=sunday, home_currency_code="CNY") is None
