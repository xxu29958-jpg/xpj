"""Real PostgreSQL statistics and FX recovery; collect locally, execute in CI."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Expense, ExpenseOffsetFact, LedgerMember, Tag
from app.services.currency_binding_service import resolve_write_capability
from app.services.tag_service import set_expense_tags


def record(db, *, amount, currency, merchant, tenant="owner", when=None, category="数码", tags="旅行"):
    when = when or datetime(2026, 9, 9, 12, tzinfo=UTC)
    expense = Expense(tenant_id=tenant, status="confirmed", amount_cents=amount,
        home_currency_code=currency, original_currency_code=currency, original_amount_minor=amount,
        merchant=merchant, category=category, value_score=5, regret_score=5,
        expense_time=when, confirmed_at=when)
    db.add(expense)
    db.flush()
    set_expense_tags(db, expense, tags)
    return expense


def read(client, identity, *, route="monthly", timezone="UTC", tag=None):
    params = {"month": "2026-09", "timezone": timezone, "home_currency_code": "JPY"}
    if tag is not None:
        params["tag"] = tag
    response = client.get("/api/stats/" + route, params=params, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()


def save_rate(client, identity, day):
    response = client.put(f"/api/exchange-rates/CNY/{day}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"currency_code": "CNY", "home_currency_code": "JPY", "rate_date": day,
            "rate_to_cny": "20", "source": "manual", "expected_row_version": 0})
    assert response.status_code == 200, response.text


def test_monthly_and_lifestyle_recover_without_relabelling_facts_or_score_values(client, identity):
    with SessionLocal() as db:
        resolve_write_capability(db)
        yuan = record(db, amount=10000, currency="CNY", merchant="Yuan shop")
        yen = record(db, amount=3000, currency="JPY", merchant="Yen shop")
        record(db, amount=99999, currency="JPY", merchant="Other ledger", tenant="tester_1")
        db.commit()
        original = (yuan.id, yuan.row_version, yuan.amount_cents, yuan.home_currency_code)
        yen_id = yen.id
    before = read(client, identity, tag="旅行")
    assert (before["total_amount_cents"], before["count"], before["home_currency_code"]) == (None, 2, "JPY")
    assert before["by_tag"] == [{"tag": "旅行", "amount_cents": None, "count": 2}]
    assert before["missing_rates"] == [{"source_currency_code": "CNY", "home_currency_code": "JPY", "rate_date": "2026-09-09"}]
    uncertain = read(client, identity, route="lifestyle")
    assert uncertain["max_expense"] is None
    assert uncertain["frequent_merchants"] == [
        {"merchant": "Yen shop", "amount_cents": 3000, "count": 1},
        {"merchant": "Yuan shop", "amount_cents": None, "count": 1}]
    assert {item["id"] for item in uncertain["best_value_expenses"]} == {original[0], yen_id}
    save_rate(client, identity, "2026-09-09")
    after = read(client, identity, tag="旅行")
    assert (after["total_amount_cents"], after["count"], after["missing_rates"]) == (5000, 2, [])
    assert after["by_tag"] == [{"tag": "旅行", "amount_cents": 5000, "count": 2}]
    lifestyle = read(client, identity, route="lifestyle")
    assert lifestyle["max_expense"]["id"] == yen_id
    assert [(item["id"], item["home_currency"], item["amount_cents"]) for item in lifestyle["best_value_expenses"]] == [
        (yen_id, "JPY", 3000), (original[0], "CNY", 10000)]
    with SessionLocal() as db:
        unchanged = db.get(Expense, original[0])
        assert (unchanged.id, unchanged.row_version, unchanged.amount_cents, unchanged.home_currency_code) == original


def test_offset_uses_own_currency_date_and_root_tags_across_timezone_boundary(client, identity):
    with SessionLocal() as db:
        resolve_write_capability(db)
        root = record(db, amount=10000, currency="CNY", merchant="Boundary", category="吃饭",
            when=datetime(2026, 8, 31, 16, 30, tzinfo=UTC))
        actor_id = db.scalar(select(Account.id).limit(1))
        db.add(ExpenseOffsetFact(tenant_id="owner", expense_id=root.id, kind="refund", status="active",
            amount_cents=300, home_currency_code="JPY", original_amount_minor=300, original_currency_code="JPY",
            accounting_date=date(2026, 9, 1), category="交通", reason="Historical refund", created_actor_account_id=actor_id))
        db.commit()
    save_rate(client, identity, "2026-09-01")
    utc = read(client, identity, tag="旅行")
    assert (utc["total_amount_cents"], utc["count"]) == (-300, 1)
    assert utc["by_category"] == [{"category": "交通", "amount_cents": -300, "count": 1}]
    shanghai = read(client, identity, tag="旅行", timezone="Asia/Shanghai")
    assert (shanghai["total_amount_cents"], shanghai["count"]) == (1700, 2)
    assert shanghai["by_tag"] == [{"tag": "旅行", "amount_cents": 1700, "count": 2}]
    assert {item["category"]: item["amount_cents"] for item in shanghai["by_category"]} == {"餐饮": 2000, "交通": -300}


def test_alias_grouping_and_deleted_tags_stay_scoped_and_viewer_can_read(client, identity):
    with SessionLocal() as db:
        resolve_write_capability(db)
        record(db, amount=10000, currency="CNY", merchant="Alias")
        record(db, amount=3000, currency="JPY", merchant="Canonical")
        record(db, amount=90000, currency="JPY", merchant="Other", tenant="tester_1")
        db.commit()
    alias = client.post("/api/merchants/aliases", headers=identity.app_headers,
        json={"canonical_merchant": "Canonical", "alias": "Alias", "enabled": True})
    assert alias.status_code == 201, alias.text
    save_rate(client, identity, "2026-09-09")
    assert read(client, identity, route="lifestyle")["frequent_merchants"] == [
        {"merchant": "Canonical", "amount_cents": 5000, "count": 2}]
    with SessionLocal() as db:
        resolve_write_capability(db)
        tag = db.scalar(select(Tag).where(Tag.tenant_id == "owner", Tag.key == "旅行"))
        tag.deleted_at = datetime(2026, 9, 10, tzinfo=UTC)
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        member.role = "viewer"
        db.commit()
    assert read(client, identity, tag="旅行")["count"] == 0
    visible = read(client, identity)
    assert (visible["total_amount_cents"], visible["count"], visible["by_tag"]) == (5000, 2, [])
    assert read(client, identity, route="lifestyle")["max_expense"]["home_currency"] == "JPY"
