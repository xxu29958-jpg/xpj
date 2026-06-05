"""Frankfurter transport + weekend/holiday rate fallback + manual sync trigger.

ADR-0027 amendment: the FX transport moves from europa.eu XML to Frankfurter
JSON (same ECB reference data, key-free, reachable from mainland China). Three
behaviours are pinned here:

1. Frankfurter JSON parses into the same EUR-based shape the cross-rate math
   already expects, and the source dispatcher defaults to it.
2. A weekend / holiday expense resolves to the most recent rate on or before its
   date instead of staying ``pending`` (ECB/Frankfurter only publish weekdays).
3. ``run_fx_sync_once`` — shared by the scheduler and the owner manual trigger —
   updates the same status counters and never raises.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local
from app.services import fx_rate_provider as provider
from app.services import fx_rate_scheduler as scheduler
from app.services.fx_rate_provider import FxFetchError, fetch_reference_rates, parse_frankfurter_rates

# A real Frankfurter daily payload (Friday 2026-05-29 — note: requesting the
# Saturday after returns this same Friday set, Frankfurter's own back-fill).
_FRANKFURTER_JSON = (
    '{"amount":1.0,"base":"EUR","date":"2026-05-29",'
    '"rates":{"USD":1.1644,"CNY":7.8793,"GBP":0.864,"JPY":186.0,"HKD":9.11,"KRW":1793.0}}'
)


def _frankfurter_response() -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = _FRANKFURTER_JSON.encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


# ─────────────────────────── transport / parsing ───────────────────────────


def test_parse_frankfurter_matches_ecb_shape() -> None:
    daily = parse_frankfurter_rates(_FRANKFURTER_JSON)
    assert daily.rate_date == date(2026, 5, 29)
    assert daily.rates_per_eur["EUR"] == Decimal("1")
    assert daily.rates_per_eur["USD"] == Decimal("1.1644")
    assert daily.rates_per_eur["CNY"] == Decimal("7.8793")


@pytest.mark.parametrize("bad", ["not json", '{"base":"EUR"}', '{"date":"2026-05-29"}'])
def test_parse_frankfurter_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_frankfurter_rates(bad)


def test_fetch_reference_rates_defaults_to_frankfurter() -> None:
    with patch.object(provider, "urlopen", return_value=_frankfurter_response()):
        daily = fetch_reference_rates()
    assert daily.rate_date == date(2026, 5, 29)
    assert daily.rates_per_eur["CNY"] == Decimal("7.8793")


# ─────────────────────── weekend / holiday fallback ────────────────────────


def _seed_global_rate(*, currency: str, rate_date: date, rate_to_home: str) -> None:
    from app.database import SessionLocal
    from app.models import FxRate
    from app.services.time_service import now_utc

    now = now_utc()
    with SessionLocal() as db:
        db.add(
            FxRate(
                source="ecb",
                home_currency_code="CNY",
                currency_code=currency,
                rate_date=rate_date,
                rate_to_home=Decimal(rate_to_home),
                provider_base_currency="EUR",
                fetched_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def test_weekend_expense_resolves_to_prior_working_day_rate(client: TestClient, *, identity) -> None:
    # Friday 2026-05-29 global rate exists; no row for the weekend.
    _seed_global_rate(currency="USD", rate_date=date(2026, 5, 29), rate_to_home="7.00000000")

    # Saturday 2026-05-30 (10:00 Asia/Shanghai) USD expense.
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "spent_at": "2026-05-30T02:00:00Z",
            "merchant": "Weekend Cafe",
            "category": "餐饮",
        },
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["fx_status"] == "ready", "weekend expense must not stay pending"
    assert Decimal(body["exchange_rate_to_cny"]) == Decimal("7.00000000")
    assert body["amount_cents"] == 70000
    assert body["exchange_rate_source"] == "ecb"


def test_expense_before_any_rate_still_pending(client: TestClient, *, identity) -> None:
    # Only a later rate exists; an expense predating it has nothing on-or-before.
    _seed_global_rate(currency="USD", rate_date=date(2026, 5, 29), rate_to_home="7.00000000")
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "spent_at": "2026-05-01T02:00:00Z",
            "merchant": "Too Early Cafe",
            "category": "餐饮",
        },
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["fx_status"] == "pending"


# ──────────────────────── run_fx_sync_once + counters ──────────────────────


def test_run_fx_sync_once_success_updates_counters(monkeypatch: pytest.MonkeyPatch, *, identity) -> None:
    from app.database import SessionLocal

    monkeypatch.setattr(scheduler, "refresh_ecb_fx_rates", lambda db: [object(), object()])
    before = scheduler.fx_rate_sync_status()
    with SessionLocal() as db:
        ok = scheduler.run_fx_sync_once(db)
    after = scheduler.fx_rate_sync_status()
    assert ok is True
    assert after.success_count == before.success_count + 1
    assert after.last_error is None
    assert after.last_success_at is not None


def test_run_fx_sync_once_network_drop_keeps_last_known(monkeypatch: pytest.MonkeyPatch, *, identity) -> None:
    from app.database import SessionLocal

    def boom(_db):  # noqa: ANN001 - test stub
        raise FxFetchError("[SSL: UNEXPECTED_EOF_WHILE_READING] simulated drop")

    monkeypatch.setattr(scheduler, "refresh_ecb_fx_rates", boom)
    before = scheduler.fx_rate_sync_status()
    with SessionLocal() as db:
        ok = scheduler.run_fx_sync_once(db)
    after = scheduler.fx_rate_sync_status()
    assert ok is False
    assert after.failed_count == before.failed_count + 1
    assert "UNEXPECTED_EOF" in (after.last_error or "")


# ─────────────────────────── owner FX panel ────────────────────────────────


def test_owner_fx_remote_returns_403(client: TestClient) -> None:
    assert client.get("/owner/fx").status_code == 403
    assert client.post("/owner/fx/refresh").status_code == 403


def test_owner_fx_manual_refresh_fetches_and_renders(local_client: TestClient) -> None:
    with patch.object(provider, "urlopen", return_value=_frankfurter_response()):
        resp = local_client.post("/owner/fx/refresh")
    assert resp.status_code == 200
    assert "已拉取最新汇率" in resp.text
    # The fetched USD→CNY cross rate (7.8793 / 1.1644) should now be listed.
    page = local_client.get("/owner/fx")
    assert page.status_code == 200
    assert "USD" in page.text
