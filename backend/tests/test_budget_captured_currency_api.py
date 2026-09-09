"""Real save entry: captured units, stale writers and accepted-response loss."""

from uuid import uuid4

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Budget, BudgetCategory


def _save(client, identity, body, key):
    return client.put("/api/budgets/monthly/2026-09", json=body,
        headers={**identity.app_headers, "Idempotency-Key": key})


def test_budget_retries_return_original_receipt_even_after_a_later_edit(client, identity):
    key = str(uuid4())
    original = {"home_currency_code": "JPY", "expected_row_version": None, "total_amount_cents": 1200,
        "rollover_amount_cents": -20, "category_budgets": [{"category": "餐饮", "amount_cents": 100}]}
    first = _save(client, identity, original, key)
    assert first.status_code == 200, first.text
    assert (first.json()["home_currency_code"], first.json()["total_amount_cents"], first.json()["row_version"]) == ("JPY", 1200, 1)
    later = _save(client, identity, {**original, "expected_row_version": 1, "total_amount_cents": 1500}, str(uuid4()))
    assert later.status_code == 200, later.text
    replay = _save(client, identity, original, key)
    assert replay.status_code == 200 and replay.json() == first.json()
    with SessionLocal() as db:
        row = db.scalar(select(Budget).where(Budget.tenant_id == "owner", Budget.month == "2026-09"))
        assert (row.home_currency_code, row.total_amount_cents, row.row_version) == ("JPY", 1500, 2)
        assert db.scalar(select(func.count(BudgetCategory.id)).where(BudgetCategory.tenant_id == "owner")) == 1
        assert db.scalar(select(func.count(ApiIdempotencyKey.id)).where(ApiIdempotencyKey.operation == "save_monthly_budget")) == 2


def test_budget_stale_or_changed_currency_cannot_replace_saved_amounts(client, identity):
    original = {"home_currency_code": "JPY", "expected_row_version": None, "total_amount_cents": 1200}
    key = str(uuid4())
    assert _save(client, identity, original, key).status_code == 200
    for changed in (
        {**original, "total_amount_cents": 999},
        {**original, "expected_row_version": 1, "home_currency_code": "CNY", "total_amount_cents": 999},
    ):
        refused = _save(client, identity, changed, str(uuid4()))
        assert refused.status_code == 409, refused.text
    reused = _save(client, identity, {**original, "total_amount_cents": 999}, key)
    assert reused.status_code == 422 and reused.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        row = db.scalar(select(Budget).where(Budget.tenant_id == "owner"))
        assert (row.home_currency_code, row.total_amount_cents, row.row_version) == ("JPY", 1200, 1)


def test_legacy_budget_payload_is_rejected_by_upgrade_gate_before_schema(client, identity):
    refused = client.put("/api/budgets/monthly/2026-09", headers=identity.auth_headers,
        json={"total_amount_cents": 1200})
    assert refused.status_code == 409
    assert refused.json()["error"] == "client_upgrade_required"
