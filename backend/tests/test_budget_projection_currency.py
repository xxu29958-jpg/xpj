"""A budget keeps its own money unit when its spending comes from other units."""

from datetime import date
from types import SimpleNamespace

from app.services import money_projection_service


def _row(amount, currency, category="餐饮"):
    return SimpleNamespace(amount_cents=amount, home_currency_code=currency,
        stream_date=date(2026, 9, 3), category=category)


def test_budget_spend_does_not_add_unconverted_units(monkeypatch):
    rows = [_row(100, "CNY"), _row(1200, "JPY"), _row(50, "CNY", "交通")]
    monkeypatch.setattr(money_projection_service, "project_recorded_amount", lambda db, **kw:
        kw["amount_minor"] if kw["source_currency"] == kw["home_currency"] else None)
    spend, missing = money_projection_service.project_category_spend(object(), tenant_id="owner", home="CNY", rows=rows)
    assert spend["餐饮"].amount_cents is None
    assert spend["餐饮"].count == 2
    assert spend["交通"].amount_cents == 50
    assert missing == {"JPY"}


def test_refund_projection_keeps_its_sign_and_captured_currency(monkeypatch):
    calls = []
    def project(db, **kw):
        calls.append(kw)
        return -6000
    monkeypatch.setattr(money_projection_service, "project_recorded_amount", project)
    spend, missing = money_projection_service.project_category_spend(object(), tenant_id="owner", home="CNY", rows=[_row(-1200, "JPY")])
    assert spend["餐饮"].amount_cents == -6000
    assert missing == set()
    assert calls[0]["source_currency"] == "JPY"
    assert calls[0]["rate_date"] == date(2026, 9, 3)
