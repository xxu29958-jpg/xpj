"""Real confirmation routes and HTML keep the original result and its list origin."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.middleware import csrf
from app.models import Expense
from app.routes import web_common, web_expense_edit, web_expense_lifecycle
from app.services import expense_edit_command_service, manual_expense_draft_presenter
from tests import test_expense_confirmation_receipt as receipt_tests

confirmation_store = receipt_tests.confirmation_store


@pytest.fixture
def confirmation_web(confirmation_store, monkeypatch):
    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"confirmation-page-test-only")
    options = [SimpleNamespace(ledger_id="owner", name="家庭账本", role="owner", is_default=True)]
    monkeypatch.setattr(web_expense_lifecycle, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_lifecycle, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_expense_lifecycle, "resolve_web_actor", lambda *args: (None, None))
    monkeypatch.setattr(web_expense_edit, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_edit, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_expense_edit, "resolve_web_actor", lambda *args: (None, None))
    monkeypatch.setattr(web_common, "require_runtime_home_currency_code", lambda db: "CNY")
    monkeypatch.setattr(web_common, "count_undated_expenses", lambda *args, **kwargs: 0)
    app = FastAPI()
    app.include_router(web_expense_lifecycle.router)
    app.include_router(web_expense_edit.router)
    app.dependency_overrides[web_expense_lifecycle.LocalOnly.dependency] = lambda: None

    def database():
        with Session(confirmation_store) as db:
            yield db

    app.dependency_overrides[web_expense_lifecycle.get_db] = database
    return TestClient(app), options


def test_confirmation_page_refresh_keeps_first_result_and_origin_after_later_correction(confirmation_store, confirmation_web):
    client, _ = confirmation_web
    key = str(uuid4())
    response = client.post("/web/expenses/42/confirm", data={"ledger_id": "owner", "expected_row_version": "4",
        "idempotency_key": key, "return_to": "pending", "return_filter": "ready"}, follow_redirects=False)
    assert response.status_code == 303
    href = response.headers["location"]
    assert f"/web/expenses/42/confirmation/{key}" in href
    assert "return_filter=ready" in href
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        current.merchant, current.amount_cents, current.row_version = "后来人工更正", 9900, 9
        db.commit()
    for _ in range(2):
        receipt = client.get(href)
        assert receipt.status_code == 200, receipt.text
        assert "这张，记好了" in receipt.text
        assert "首次便利店" in receipt.text and "128.60" in receipt.text
        assert "后来人工更正" not in receipt.text and "99.00" not in receipt.text
        assert "JPY" in receipt.text and "2,850" in receipt.text
        assert "/web/pending?ledger_id=owner&amp;filter=ready" in receipt.text
        assert "return_receipt_key=" + key in receipt.text
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).row_version == 9


def test_original_confirmation_checks_browser_binding_and_permission_before_replay(confirmation_store, confirmation_web, monkeypatch):
    client, options = confirmation_web
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "owner", "deviceId": "browser"}

    def local(request: web_expense_lifecycle.Request):
        request.state.web_session_auth = SimpleNamespace(ledger_id="owner")

    client.app.dependency_overrides[web_expense_lifecycle.LocalOnly.dependency] = local
    monkeypatch.setattr(manual_expense_draft_presenter, "manual_draft_scope", lambda *args: scope)
    key = str(uuid4())
    fields = {"ledger_id": "owner", "expected_row_version": "4", "idempotency_key": key,
        "draft_scope": json.dumps({**scope, "deviceId": "previous-browser"}), "return_to": "pending", "return_filter": "ready"}
    headers = {"Accept": "application/json"}
    wrong_browser = client.post("/web/expenses/42/confirm", data=fields, headers=headers, follow_redirects=False)
    assert wrong_browser.status_code == 409, wrong_browser.text
    assert wrong_browser.json()["error"] == "session_binding_changed"
    with Session(confirmation_store) as db:
        assert db.get(Expense, 42).status == "pending"
    fields["draft_scope"] = json.dumps(scope)
    accepted = client.post("/web/expenses/42/confirm", data=fields, headers=headers)
    assert accepted.status_code == 200, accepted.text
    original = accepted.json()
    assert original["ack"] == {"scope": scope, "clientRef": key}
    assert original["receipt"]["amount_cents"] == 12860
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        current.amount_cents, current.merchant, current.row_version = 9900, "后来事实", 9
        db.commit()
    options[0].role = "viewer"
    revoked = client.post("/web/expenses/42/confirm", data=fields, headers=headers)
    assert revoked.status_code == 403, revoked.text
    assert revoked.json()["draft_result"] == "blocked"
    # Read permission can inspect the accepted receipt without resubmitting a command.
    assert client.get(original["next"]).status_code == 200
    options[0].role = "owner"
    replay = client.post("/web/expenses/42/confirm", data=fields, headers=headers)
    assert replay.json() == original
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).amount_cents, db.get(Expense, 42).row_version) == (9900, 9)


def test_original_save_binding_and_acceptance_survive_later_confirmation(confirmation_store, confirmation_web, monkeypatch):
    client, options = confirmation_web
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "owner", "deviceId": "browser"}

    def local(request: web_expense_edit.Request):
        request.state.web_session_auth = SimpleNamespace(ledger_id="owner")

    def update(db, expense_id, tenant_id, payload, **kwargs):
        current = db.get(Expense, expense_id)
        current.merchant, current.row_version = payload.merchant, current.row_version + 1
        return current

    client.app.dependency_overrides[web_expense_edit.LocalOnly.dependency] = local
    monkeypatch.setattr(manual_expense_draft_presenter, "manual_draft_scope", lambda *args: scope)
    monkeypatch.setattr(expense_edit_command_service, "update_expense", update)
    monkeypatch.setattr(expense_edit_command_service, "prepare_pending_expense_fx", lambda *args, **kwargs: None)
    key = str(uuid4())
    fields = {"ledger_id": "owner", "expected_row_version": "4", "idempotency_key": key,
        "merchant": "保存的商家", "amount_yuan": "2850", "original_currency": "JPY", "category": "购物",
        "draft_scope": json.dumps({**scope, "deviceId": "previous-browser"}), "return_to": "pending", "return_filter": "ready"}
    headers = {"Accept": "application/json"}
    wrong_browser = client.post("/web/expenses/42/save", data=fields, headers=headers, follow_redirects=False)
    assert wrong_browser.status_code == 409, wrong_browser.text
    assert wrong_browser.json()["error"] == "session_binding_changed"
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).merchant, db.get(Expense, 42).row_version) == ("首次便利店", 4)
    fields["draft_scope"] = json.dumps(scope)
    accepted = client.post("/web/expenses/42/save", data=fields, headers=headers, follow_redirects=False)
    assert accepted.status_code == 200, accepted.text
    original = accepted.json()
    assert original["ack"] == {"scope": scope, "clientRef": key}
    assert original["receipt"] == {"operation": "patch_expense", "expense_id": 42, "accepted": True}
    assert "new_expensereview=1" in original["next"] and "return_filter=ready" in original["next"]
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.status, current.row_version) == ("保存的商家", "pending", 5)
        current.merchant, current.status, current.row_version = "后来确认", "confirmed", 9
        db.commit()
    options[0].role = "viewer"
    revoked = client.post("/web/expenses/42/save", data=fields, headers=headers)
    assert revoked.status_code == 403 and revoked.json()["draft_result"] == "blocked"
    options[0].role = "owner"
    replay = client.post("/web/expenses/42/save", data=fields, headers=headers)
    assert replay.json() == original
    with Session(confirmation_store) as db:
        assert (db.get(Expense, 42).merchant, db.get(Expense, 42).row_version) == ("后来确认", 9)
