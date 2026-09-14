"""Dated provider transport and cache preparation, without a database or network."""

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.models import FxRate
from app.services import fx_rate_provider as provider

FRIDAY = date(2026, 5, 29)
SUNDAY = date(2026, 5, 31)
MONDAY = date(2026, 6, 1)
RATES = provider.EcbDailyRates(FRIDAY, {"EUR": Decimal("1"), "USD": Decimal("1.1644"), "CNY": Decimal("7.8793")})
JSON_RATES = '{"base":"EUR","date":"2026-05-29","rates":{"USD":1.1644,"CNY":7.8793}}'
HISTORY = (
    '<Envelope xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube>'
    '<Cube time="2026-06-01"><Cube currency="CNY" rate="8"/></Cube>'
    '<Cube time="2026-05-28"><Cube currency="CNY" rate="7.7"/></Cube>'
    '<Cube time="2026-05-29"><Cube currency="CNY" rate="7.8793"/>'
    '<Cube currency="USD" rate="1.1644"/></Cube></Cube></Envelope>'
)


@pytest.fixture()
def transport(monkeypatch):
    config = SimpleNamespace(
        fx_rate_source="frankfurter",
        fx_rate_frankfurter_url="https://mirror.example.test/cache/v1/latest?base=USD&amount=2&symbols=CNY%2CUSD",
        fx_rate_ecb_url="https://mirror.example.test/ecb/eurofxref-daily.xml?mirror=one",
    )
    monkeypatch.setattr(provider, "get_settings", lambda: config)
    monkeypatch.setattr(provider, "now_utc", lambda: datetime(2026, 6, 1, 12, tzinfo=UTC))
    requests = []

    def respond(content):
        def read(request, timeout):
            requests.append((request.full_url, timeout))
            return BytesIO(content.encode())
        monkeypatch.setattr(provider, "urlopen", read)

    return config, requests, respond


def test_dated_frankfurter_keeps_transport_and_requests_the_original_day(transport):
    _, requests, respond = transport
    respond(JSON_RATES)
    daily = provider.fetch_reference_rates_for_date(SUNDAY)
    assert daily == RATES
    target = urlsplit(requests[0][0])
    assert (target.netloc, target.path) == ("mirror.example.test", "/cache/v1/2026-05-31")
    assert parse_qs(target.query) == {"base": ["EUR"], "amount": ["1"], "symbols": ["CNY,USD"]}
    assert requests[0][1] == provider.FETCH_TIMEOUT_SECONDS


def test_ecb_history_selects_the_latest_eligible_publication_not_the_first_cube(transport):
    config, requests, respond = transport
    config.fx_rate_source = "ecb"
    respond(HISTORY)
    assert provider.fetch_reference_rates_for_date(SUNDAY) == RATES
    assert requests[0][0] == "https://mirror.example.test/ecb/eurofxref-hist.xml?mirror=one"


@pytest.mark.parametrize("endpoint", ["custom-latest.xml", "rates", ""])
def test_custom_ecb_daily_endpoint_cannot_claim_historical_coverage(transport, endpoint):
    config, requests, respond = transport
    config.fx_rate_source = "ecb"
    config.fx_rate_ecb_url = f"https://mirror.example.test/ecb/{endpoint}"
    respond('<Envelope><Cube><Cube time="2026-05-01"><Cube currency="USD" rate="1"/>'
        '<Cube currency="CNY" rate="7"/></Cube></Cube></Envelope>')
    with pytest.raises(ValueError, match="historical"):
        provider.fetch_reference_rates_for_date(SUNDAY)
    assert requests == []


@pytest.mark.parametrize("endpoint", ["eurofxref-daily.xml", "eurofxref-hist-90d.xml", "eurofxref-hist.xml"])
def test_known_ecb_endpoint_fetches_history_through_the_configured_mirror(transport, endpoint):
    config, requests, respond = transport
    config.fx_rate_source = "ecb"
    config.fx_rate_ecb_url = f"https://mirror.example.test/ecb/{endpoint}?mirror=one"
    respond(HISTORY)
    assert provider.fetch_reference_rates_for_date(SUNDAY) == RATES
    assert requests[0][0] == "https://mirror.example.test/ecb/eurofxref-hist.xml?mirror=one"


def test_ecb_missing_history_does_not_borrow_a_later_rate(transport):
    config, _, respond = transport
    config.fx_rate_source = "ecb"
    respond(HISTORY)
    with pytest.raises(ValueError, match="no rate on or before"):
        provider.fetch_reference_rates_for_date(date(2026, 5, 27))


@pytest.mark.parametrize("body", [
    JSON_RATES.replace("2026-05-29", "2026-06-01"),
    JSON_RATES.replace('"EUR"', '"USD"'),
    JSON_RATES.replace("1.1644", "0"),
    JSON_RATES.replace("1.1644", "-1"),
    JSON_RATES.replace("1.1644", "NaN"),
    JSON_RATES.replace("1.1644", "Infinity"),
])
def test_invalid_dated_reference_is_rejected_before_any_cache_write(transport, body):
    _, _, respond = transport
    respond(body)
    with pytest.raises(ValueError):
        provider.fetch_reference_rates_for_date(SUNDAY)


def test_future_provider_date_is_not_clamped_to_today(transport):
    _, requests, respond = transport
    respond(JSON_RATES)
    with pytest.raises(ValueError, match="future provider date"):
        provider.fetch_reference_rates_for_date(date(2026, 6, 2))
    assert requests == []


@pytest.mark.parametrize("requested,coverage", [(SUNDAY, SUNDAY), (MONDAY, None), (date(2026, 6, 2), None)])
def test_cache_extends_only_closed_dates_and_returns_current_quote_to_the_caller(transport, monkeypatch, requested, coverage):
    writes = []

    def store(_db, **values):
        writes.append(values)
        return FxRate(**values)

    monkeypatch.setattr(provider, "upsert_fx_rate", store)
    db = Mock()
    rows = provider.cache_reference_rates_for_date(
        db, RATES, requested_date=requested, home_currency_code="CNY", currencies={"USD"},
    )
    assert len(rows) == 1
    assert rows[0].rate_date == FRIDAY
    assert rows[0].rate_to_home == Decimal("6.76683270")
    assert writes[0]["provider_rate"] == Decimal("1.1644")
    assert writes[0]["verified_through"] == coverage
    assert db.mock_calls == []


def test_unavailable_pair_is_validated_before_caching_any_rows(transport, monkeypatch):
    store = Mock()
    monkeypatch.setattr(provider, "upsert_fx_rate", store)
    with pytest.raises(ValueError, match="missing"):
        provider.cache_reference_rates_for_date(
            Mock(), RATES, requested_date=SUNDAY, home_currency_code="CNY", currencies={"USD", "JPY"},
        )
    store.assert_not_called()
