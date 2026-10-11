"""Only an original creation receipt may acknowledge a browser's saved intent."""

import json
from datetime import timedelta
from html import unescape
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError, app_error_handler
from app.models import ApiIdempotencyKey, Expense
from app.routes import web_expense_create
from app.schemas import ExpenseResponse
from app.services import manual_expense_draft_presenter as presenter
from app.services.manual_expense_receipt import _manual_receipt_key
from tests import test_web_expense_confirmation_page as pages

confirmation_store = pages.confirmation_store
confirmation_web = pages.confirmation_web


@pytest.mark.parametrize("receipt_id", [None, 99, 7])
def test_opening_current_fact_requires_matching_original_receipt_before_draft_ack(monkeypatch, receipt_id):
    auth = SimpleNamespace(device_id=41, ledger_id="ledger")
    ref = "a" * 32
    # This is the later current fact, not the first accepted response.
    expense = SimpleNamespace(id=7, tenant_id="ledger", source="手动记账",
        draft_idempotency_key=f"41:{ref}", amount_cents=9900, row_version=4)
    receipt = None if receipt_id is None else SimpleNamespace(id=receipt_id, amount_cents=1200, row_version=1)
    monkeypatch.setattr(presenter, "read_manual_creation_receipt", lambda *_a, **_k: receipt, raising=False)
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
        "ledgerId": "ledger", "deviceId": "device"}
    monkeypatch.setattr(presenter, "manual_draft_scope", lambda *_a: scope)

    ack = presenter.manual_draft_ack(object(), auth, expense)

    assert ack == ({"scope": scope, "clientRef": ref,
        "originalTarget": {"expenseId": 7, "rowVersion": 1},
        "uploadMaxBytes": get_settings().max_upload_size_bytes} if receipt_id == expense.id else None)


@pytest.fixture
def manual_receipt_page(confirmation_web, monkeypatch):
    client, options = confirmation_web
    scope = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
        "ledgerId": "owner", "deviceId": "browser"}
    def local(request: web_expense_create.Request):
        request.state.web_session_auth = SimpleNamespace(ledger_id="owner", device_id=7, device_public_id="browser")
    client.app.dependency_overrides[web_expense_create.LocalOnly.dependency] = local
    client.app.add_exception_handler(AppError, app_error_handler)
    client.app.include_router(web_expense_create.router)
    monkeypatch.setattr(web_expense_create, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_create, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(presenter, "manual_draft_scope", lambda *args: scope)
    return client, scope, options


def _seed_original(confirmation_store, status):
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        current.source, current.status, current.draft_idempotency_key = "手动记账", status, "7:" + "a" * 32
        if status == "pending":
            current.amount_cents, current.fx_status = None, "pending"
        receipt = ExpenseResponse.model_validate(current).model_dump(mode="json")
        db.add(ApiIdempotencyKey(tenant_id="owner", idempotency_key=_manual_receipt_key(7, "a" * 32),
            operation="create_manual_expense", request_fingerprint="b" * 64, status="succeeded",
            resource_type="expense", resource_id="42", response_body=receipt,
            expires_at=current.created_at + timedelta(days=30)))
        current.merchant, current.amount_cents, current.row_version, current.status = "后来人工修改", 9900, 9, "confirmed"
        db.commit()
        return receipt


def _result_query(scope):
    return {"ledger_id": "owner", "client_ref": "a" * 32, "draft_scope": json.dumps(scope), "return_to": "confirmed"}


@pytest.mark.parametrize("status", ["confirmed", "pending"])
def test_reading_manual_first_result_after_later_edits_is_read_only_even_for_viewer(
    manual_receipt_page, confirmation_store, status,
):
    client, scope, options = manual_receipt_page
    receipt = _seed_original(confirmation_store, status)
    options[0].role = "viewer"
    response = client.get("/web/expenses/new/result", params=_result_query(scope))
    assert response.status_code == 200, response.text
    body = unescape(response.text)
    assert "首次便利店" in body and "后来人工修改" not in body and "99.00" not in body
    assert "JPY" in body and "2,850" in body
    assert ("创建时已入账" if status == "confirmed" else "创建时待核对，尚未入账") in body
    assert ("128.60" in body) == (status == "confirmed")
    assert 'data-manual-draft-ack=' in body and '"clientRef": "' + "a" * 32 + '"' in body
    assert '"originalTarget": {"expenseId": 42, "rowVersion": 4}' in body
    assert "/web/expenses/42/edit?ledger_id=owner&return_to=confirmed" in body
    assert response.headers["cache-control"] == "no-store"
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.amount_cents, current.row_version) == ("后来人工修改", 9900, 9)
        assert db.scalar(select(ApiIdempotencyKey)).response_body == receipt


@pytest.mark.parametrize("legacy", [False, True])
def test_missing_manual_receipt_keeps_unknown_result_and_original_return(manual_receipt_page, confirmation_store, legacy):
    client, scope, _ = manual_receipt_page
    if legacy:
        _seed_original(confirmation_store, "confirmed")
        with Session(confirmation_store) as db:
            db.scalar(select(ApiIdempotencyKey)).response_body = None
            db.commit()
    response = client.get("/web/expenses/new/result", params=_result_query(scope))
    assert response.status_code == 200, response.text
    body = unescape(response.text)
    assert "不能据此判断没有保存" in body and "data-manual-draft-ack=" not in body
    assert "/web/expenses/new?ledger_id=owner&return_to=confirmed#manual-" + "a" * 32 in body
    assert ("/web/expenses/42/edit" in body) == legacy
    assert "后来人工修改" not in body


@pytest.mark.parametrize("axis", ["deviceId", "clientGeneration"])
def test_manual_result_refuses_changed_binding_before_exposing_first_result(manual_receipt_page, confirmation_store, axis):
    client, scope, _ = manual_receipt_page
    _seed_original(confirmation_store, "confirmed")
    response = client.get("/web/expenses/new/result", params=_result_query({**scope, axis: "changed"}))
    assert response.status_code == 409, response.text
    assert "首次便利店" not in response.text and "data-manual-draft-ack=" not in response.text
