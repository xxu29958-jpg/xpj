"""Saved arrangements survive replacement, retries and the recycle round trip."""

from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Budget, BudgetRevision


def _save(client, identity, **changes):
    body = {"home_currency_code": "JPY", "expected_row_version": None,
        "total_amount_cents": 1200, "rollover_amount_cents": -20,
        "non_monthly_amount_cents": 100, "excluded_categories": ["旅行"],
        "category_budgets": [{"category": "餐饮", "amount_cents": 300}]}
    body.update(changes)
    key = str(uuid4())
    response = client.put("/api/budgets/monthly/2026-09", json=body,
        headers={**identity.app_headers, "Idempotency-Key": key})
    assert response.status_code == 200, response.text
    return body, key, response.json()


def _history(client, identity, **params):
    response = client.get("/api/budgets/monthly/2026-09/history", params=params, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_replacement_and_ack_loss_preserve_original_budget_and_categories(client, identity):
    original, key, receipt = _save(client, identity)
    _save(client, identity, expected_row_version=1, total_amount_cents=1500,
        category_budgets=[{"category": "交通", "amount_cents": 200}], excluded_categories=[])
    replay = client.put("/api/budgets/monthly/2026-09", json=original,
        headers={**identity.app_headers, "Idempotency-Key": key})
    assert replay.status_code == 200 and replay.json() == receipt
    first_page = _history(client, identity, limit=1)
    assert first_page["items"][0]["change_kind"] == "edit"
    assert first_page["items"][0]["snapshot"]["total_amount_cents"] == 1500
    second_page = _history(client, identity, before_version=first_page["next_before_version"], limit=1)
    original_snapshot = second_page["items"][0]["snapshot"]
    assert original_snapshot == {key: value for key, value in original.items() if key != "expected_row_version"} | {"archived": False}
    assert second_page["items"][0]["change_kind"] == "create"
    assert second_page["next_before_version"] is None
    refused = client.put("/api/budgets/monthly/2026-09", json=original,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())})
    assert refused.status_code == 409
    assert len(_history(client, identity)["items"]) == 2


def test_archive_and_restore_are_history_without_replacing_the_saved_arrangement(client, identity):
    _save(client, identity)
    archived = client.request("DELETE", "/api/budgets/monthly/2026-09",
        json={"expected_row_version": 1}, headers=identity.app_headers)
    assert archived.status_code == 200, archived.text
    assert _history(client, identity)["items"][0]["snapshot"]["archived"] is True
    for _ in range(2):
        restored = client.post("/api/recycle-bin/restore", json={"kind": "monthly_budget",
            "resource_id": "2026-09", "expected_row_version": 2}, headers=identity.app_headers)
        assert restored.status_code == 200, restored.text
    history = _history(client, identity)
    assert [item["change_kind"] for item in history["items"]] == ["restore", "archive", "create"]
    assert {item["snapshot"]["total_amount_cents"] for item in history["items"]} == {1200}
    assert history["items"][0]["snapshot"]["archived"] is False
    with SessionLocal() as db:
        budget = db.scalar(select(Budget).where(Budget.tenant_id == "owner", Budget.month == "2026-09"))
        assert budget.row_version == 3
        actors = list(db.scalars(select(BudgetRevision.actor_account_id).where(
            BudgetRevision.budget_id == budget.id).order_by(BudgetRevision.row_version)))
        assert actors[0] is not None
        assert actors == [actors[0]] * 3


def test_missing_month_has_an_honest_empty_history_and_rejects_invalid_cursor(client, identity):
    assert _history(client, identity)["items"] == []
    refused = client.get("/api/budgets/monthly/2026-09/history", params={"before_version": 0}, headers=identity.app_headers)
    assert refused.status_code == 422


def test_history_remains_ledger_scoped_and_visible_to_readers(client, identity):
    from app.models import LedgerMember

    _save(client, identity)
    other = client.get("/api/budgets/monthly/2026-09/history", headers=identity.gray_app_headers)
    assert other.status_code == 200 and other.json()["items"] == []
    with SessionLocal.begin() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        member.role = "viewer"
    assert len(_history(client, identity)["items"]) == 1
    refused = client.put("/api/budgets/monthly/2026-09", json={"home_currency_code": "JPY",
        "expected_row_version": 1, "total_amount_cents": 999},
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())})
    assert refused.status_code == 403


def test_failed_history_publication_rolls_back_the_budget_and_categories(client, identity, monkeypatch):
    from app.errors import AppError
    from app.services import budget_command_service

    original, _, _ = _save(client, identity)

    def refuse(*args, **kwargs):
        raise AppError("state_conflict", status_code=409)

    monkeypatch.setattr(budget_command_service, "record_budget_revision", refuse)
    response = client.put("/api/budgets/monthly/2026-09",
        json={**original, "expected_row_version": 1, "total_amount_cents": 999, "category_budgets": []},
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())})
    assert response.status_code == 409
    current = client.get("/api/budgets/monthly", params={"month": "2026-09"}, headers=identity.app_headers).json()
    assert (current["row_version"], current["total_amount_cents"], current["category_budgets"][0]["category"]) == (1, 1200, "餐饮")
    assert len(_history(client, identity)["items"]) == 1
