"""Real PostgreSQL report projection and rate recovery; collect locally only."""

from datetime import UTC, datetime
from uuid import uuid4

from app.database import SessionLocal
from app.models import Expense


def test_mixed_period_report_and_csv_recover_after_rate_without_rewriting_history(client, identity):
    when = datetime(2026, 9, 7, 12, tzinfo=UTC)
    with SessionLocal() as db:
        yen = Expense(tenant_id="owner", status="confirmed", merchant="Yen shop", category="餐饮",
            amount_cents=1000, home_currency_code="JPY", original_currency_code="JPY", original_amount_minor=1000,
            expense_time=when, confirmed_at=when)
        yuan = Expense(tenant_id="owner", status="confirmed", merchant="Yuan shop", category="交通",
            amount_cents=2000, home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=2000,
            expense_time=when, confirmed_at=when)
        db.add_all([yen, yuan])
        db.commit()
        original_id = yuan.id
    query = "?month=2026-09&timezone=UTC&home_currency_code=JPY&ranking_metric=amount"
    response = client.get("/api/reports/overview" + query, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    before = response.json()
    assert before["total_amount_cents"] is None
    assert before["count"] == 2
    assert before["merchant_ranking"] == []
    assert before["missing_rates"] == [{"source_currency_code": "CNY", "home_currency_code": "JPY", "rate_date": "2026-09-07"}]
    saved = client.put("/api/exchange-rates/CNY/2026-09-07", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"currency_code": "CNY", "home_currency_code": "JPY", "rate_date": "2026-09-07", "rate_to_cny": "20",
            "source": "manual", "expected_row_version": 0})
    assert saved.status_code == 200, saved.text
    response = client.get("/api/reports/overview" + query, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["home_currency_code"] == "JPY"
    assert after["total_amount_cents"] == 1400
    assert after["missing_rates"] == []
    assert [(row["merchant"], row["amount_cents"]) for row in after["merchant_ranking"]] == [("Yen shop", 1000), ("Yuan shop", 400)]
    exported = client.get("/api/reports/overview.csv" + query, headers=identity.app_headers)
    assert exported.status_code == 200
    assert "summary,home_currency_code,JPY" in exported.text
    assert "summary,total_amount_cents,1400" in exported.text
    with SessionLocal() as db:
        original = db.get(Expense, original_id)
        assert (original.amount_cents, original.home_currency_code, original.original_amount_minor) == (2000, "CNY", 2000)
