"""Explicit merchant aliases affect advice and rejects, never saved facts."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.database import SessionLocal
from app.models import Account, Expense, LedgerMember, MerchantAlias
from app.services.learning_service import compute_category_suggestion
from app.services.merchant_alias_service import create_merchant_alias, update_merchant_alias


def _history(client, identity, intent="manual"):
    rows = []
    for index, merchant in enumerate(("连锁咖啡", "chain cafe", "CHAIN  CAFE（自动）")):
        response = client.post("/api/expenses/manual", headers=identity.app_headers, json={
            "client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1200 + index,
            "merchant": merchant, "category": "餐饮", "category_choice": intent,
            "spent_at": (datetime.now(UTC) - timedelta(days=index + 1)).isoformat()})
        assert response.status_code == 200, response.text
        rows.append(response.json())
    return rows


def _next(client, identity, merchant="连锁咖啡", note=""):
    response = client.post("/api/expenses/notification-drafts", headers=identity.app_headers, json={
        "source": "alipay", "notification_key": str(uuid4()), "amount_cents": 1900, "merchant": merchant})
    assert response.status_code == 200, response.text
    return client.get(f"/api/expenses/{response.json()['id']}", headers=identity.app_headers).json()


def _alias():
    with SessionLocal() as db:
        item = create_merchant_alias(db, tenant_id="owner", canonical_merchant="连锁咖啡", alias="chain cafe")
        db.commit()
        return item.id


@pytest.mark.parametrize("intent", ["manual", "one_off"])
def test_alias_enables_only_independent_personal_examples_and_disable_is_immediate(client, identity, intent):
    history = _history(client, identity, intent)
    assert _next(client, identity)["category_suggestion"] is None
    alias_id = _alias()
    proposed = _next(client, identity)
    assert bool(proposed["category_suggestion"]) == (intent == "manual")
    if intent == "manual":
        assert proposed["category_suggestion"]["sample_size"] == 3
        assert proposed["category_suggestion"]["category"] == "餐饮"
    with SessionLocal() as db:
        other = Account(display_name="其他成员")
        db.add(other)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=other.id, role="member"))
        db.flush()
        assert compute_category_suggestion(db, tenant_id="owner", merchant="chain cafe", actor_account_id=other.id) is None
        alias = db.get(MerchantAlias, alias_id)
        update_merchant_alias(db, alias, expected_row_version=alias.row_version, enabled=False)
        for original in history:
            row = db.get(Expense, original["id"])
            assert (row.merchant, row.category, row.amount_cents, row.row_version) == (
                original["merchant"], original["category"], original["amount_cents"], original["row_version"])
    assert _next(client, identity)["category_suggestion"] is None


def test_rejects_under_an_alias_suppress_the_same_canonical_merchant(client, identity):
    _history(client, identity)
    _alias()
    for merchant in ("chain cafe", "CHAIN  CAFE（自动）"):
        proposed = _next(client, identity, merchant)
        advice = proposed["category_suggestion"]
        assert advice is not None
        response = client.post(f"/api/expenses/{proposed['id']}/suggestions/{advice['decision_public_id']}/reject",
            headers=identity.app_headers)
        assert response.status_code == 200, response.text
    assert _next(client, identity)["category_suggestion"] is None


@pytest.mark.parametrize("suffix", ["(Auto)", "（Auto）"])
def test_notification_suffix_preserves_alias_resolution_for_the_target(client, identity, suffix):
    _history(client, identity)
    _alias()
    assert _next(client, identity, "CHAIN CAFE" + suffix)["category_suggestion"]["sample_size"] == 3


def test_pending_batch_resolves_historical_names_only_once(client, identity):
    from sqlalchemy import event

    from app.database import engine

    _history(client, identity)
    _alias()
    for _ in range(4):
        _next(client, identity, "chain cafe")
    scans = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if "SELECT DISTINCT expenses.merchant" in statement:
            scans.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        response = client.get("/api/expenses/pending", headers=identity.app_headers)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert response.status_code == 200, response.text
    assert len(scans) == 1
    assert len(response.json()) >= 4
