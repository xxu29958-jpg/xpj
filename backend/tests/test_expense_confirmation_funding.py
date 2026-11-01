"""Real PostgreSQL boundaries for single-payer review and atomic offline replay."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models import AccountMovement, ApiIdempotencyKey, Expense, ExpenseFunding
from tests.test_funds_accounts import _create_funds_account


def _draft(client, identity, amount=2933):
    response = client.post("/api/expenses/notification-drafts", headers=identity.app_headers, json={
        "source": "alipay", "notification_key": str(uuid4()), "amount_cents": amount,
        "merchant": "回归交易", "original_currency_code": "CNY", "original_amount_minor": amount,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _selection(account, **changes):
    return {"component_id": str(uuid4()), "account_public_id": account["public_id"],
        "account_row_version": account["row_version"], "expense_currency_code": "CNY",
        "account_currency_code": account["currency_code"], **changes}


def _submit(client, identity, expense, body, key):
    return client.post(f"/api/expenses/{expense['id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": expense["row_version"], **body})


def _assert_uncommitted(expense, key):
    with SessionLocal() as db:
        row = db.get(Expense, expense["id"])
        assert (row.status, row.row_version, row.original_amount_minor, row.merchant) == (
            "pending", expense["row_version"], expense["original_amount_minor"], expense["merchant"])
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.expense_id == row.id)) == 0
        assert db.scalar(select(func.count()).select_from(AccountMovement).where(AccountMovement.funding_id.is_not(None))) == 0
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None


@pytest.mark.parametrize("amount", [1000, 1290, 2933])
def test_single_cny_payer_uses_authoritative_amount_and_replays_once(client, identity, amount):
    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense = _draft(client, identity, amount)
    body, key = {"funding": [_selection(account)]}, str(uuid4())
    accepted = _submit(client, identity, expense, body, key)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()["confirmation_receipt"]
    assert receipt["original_amount_minor"] == amount and receipt["status"] == "confirmed"
    # The sender lost its response and still has the original expense/account versions.
    replay = _submit(client, identity, expense, body, key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["confirmation_receipt"] == receipt
    account_read = client.get("/api/funds/accounts/" + account["public_id"], headers=identity.app_headers).json()
    assert account_read["balance_minor"] == 100000 - amount
    with SessionLocal() as db:
        parts = list(db.scalars(select(ExpenseFunding).where(ExpenseFunding.expense_id == expense["id"])))
        assert len(parts) == 1
        assert (parts[0].expense_amount_minor, parts[0].account_amount_minor) == (amount, amount)
        assert db.scalar(select(func.count()).select_from(AccountMovement).where(AccountMovement.funding_id == parts[0].id)) == 1
    duplicate = _submit(client, identity, expense, body, str(uuid4()))
    assert duplicate.status_code == 409
    changed = _submit(client, identity, expense, {"funding": [_selection(account)]}, key)
    assert changed.status_code == 422 and changed.json()["error"] == "idempotency_key_reused"


def test_atomic_edits_and_funding_rollback_then_retry_with_original_draft(client, identity):
    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense = _draft(client, identity)
    key = str(uuid4())
    part = _selection(account, expense_amount_minor=1000, account_amount_minor=1000)
    changes = {"original_amount_minor": 1290, "merchant": "核对后的商户"}
    body = {"changes": changes, "funding": [part]}
    failed = _submit(client, identity, expense, body, key)
    assert failed.status_code == 422 and failed.json()["error"] == "funding_amount_mismatch", failed.text
    assert failed.json()["field"] == "funding.expense_amount_minor"
    assert failed.json()["expected_total_minor"] == 1290
    _assert_uncommitted(expense, key)
    # Explicit failed command is repaired and submitted without a second financial effect.
    repaired = {"changes": changes, "funding": [_selection(account)]}
    accepted = _submit(client, identity, expense, repaired, key)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["original_amount_minor"] == 1290
    assert accepted.json()["merchant"] == "核对后的商户"
    assert _submit(client, identity, expense, repaired, key).json()["confirmation_receipt"] == accepted.json()["confirmation_receipt"]
    assert client.get("/api/funds/accounts/" + account["public_id"], headers=identity.app_headers).json()["balance_minor"] == 98710


def test_split_missing_amount_names_the_actual_field_and_preserves_draft(client, identity):
    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense, key = _draft(client, identity), str(uuid4())
    response = _submit(client, identity, expense, {"funding": [_selection(account), _selection(account)]}, key)
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "funding_amount_required"
    assert response.json()["field"] == "funding.0.expense_amount_minor"
    _assert_uncommitted(expense, key)


def test_home_amount_authority_does_not_require_a_redundant_original_amount(client, identity):
    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense = _draft(client, identity)
    with SessionLocal() as db:
        db.get(Expense, expense["id"]).original_amount_minor = None
        db.commit()
    response = _submit(client, identity, expense, {"funding": [_selection(account)]}, str(uuid4()))
    assert response.status_code == 200, response.text
    parts = client.get(f"/api/expenses/{expense['id']}/funding", headers=identity.app_headers).json()["parts"]
    assert len(parts) == 1 and parts[0]["expense_amount_minor"] == parts[0]["account_amount_minor"] == 2933


@pytest.mark.parametrize("fault", ["account_occ", "expense_occ", "account_currency", "foreign_ledger"])
def test_simple_payer_preserves_version_currency_and_ledger_guards(client, identity, fault):
    from dataclasses import replace

    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense, key = _draft(client, identity), str(uuid4())
    selected = _selection(account)
    body = {"funding": [selected]}
    if fault == "account_occ":
        selected["account_row_version"] += 1
    elif fault == "expense_occ":
        body["expected_row_version"] = expense["row_version"] + 1
    elif fault == "account_currency":
        selected["account_currency_code"] = "USD"
    else:
        foreign = _create_funds_account(client, replace(identity, app_token=identity.tenant_app_token), "其他账本", "bank", 100000)
        body["funding"] = [_selection(foreign)]
    refused = _submit(client, identity, expense, body, key)
    assert refused.status_code == (404 if fault == "foreign_ledger" else 409), refused.text
    _assert_uncommitted(expense, key)


def test_opening_coverage_and_split_amounts_keep_their_existing_meaning(client, identity):
    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense = _draft(client, identity)
    body = {"changes": {"time_input": {"precision": "date_only", "calendar_revision": account["calendar_revision"],
        "user_local_date": str(date.today() - timedelta(days=1))}},
        "funding": [_selection(account, included_in_opening=True)]}
    accepted = _submit(client, identity, expense, body, str(uuid4()))
    assert accepted.status_code == 200, accepted.text
    account = client.get("/api/funds/accounts/" + account["public_id"], headers=identity.app_headers).json()
    assert account["balance_minor"] == 100000
    with SessionLocal() as db:
        assert db.scalar(select(ExpenseFunding).where(ExpenseFunding.expense_id == expense["id"])).included_in_opening
        assert db.scalar(select(func.count()).select_from(AccountMovement).where(AccountMovement.funding_id.is_not(None))) == 0
    other = _create_funds_account(client, identity, "第二付款来源", "bank", 20000)
    expense = _draft(client, identity)
    body = {"funding": [_selection(account, expense_amount_minor=1000), _selection(other, expense_amount_minor=1933)]}
    accepted = _submit(client, identity, expense, body, str(uuid4()))
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.expense_id == expense["id"])) == 2


def test_receipt_failure_rolls_back_edits_confirmation_and_deduction(client, identity, monkeypatch):
    from app.services import expense_review_command_service as owner

    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense, key = _draft(client, identity), str(uuid4())
    def fail(*args, **kwargs):
        raise SQLAlchemyError("injected receipt persistence failure")
    monkeypatch.setattr(owner, "mark_idempotency_succeeded", fail)
    with pytest.raises(SQLAlchemyError, match="injected receipt"):
        _submit(client, identity, expense, {"changes": {"merchant": "尚未提交"}, "funding": [_selection(account)]}, key)
    _assert_uncommitted(expense, key)


def test_cleanup_failure_cannot_report_rejection_after_financial_commit(client, identity, monkeypatch):
    from app.services import expense_review_command_service as owner

    account = _create_funds_account(client, identity, "厦门", "bank", 100000)
    expense, key = _draft(client, identity), str(uuid4())
    body = {"funding": [_selection(account)]}
    def fail(*args):
        raise SQLAlchemyError("injected cleanup failure")
    monkeypatch.setattr(owner, "cleanup_after_confirm", fail)
    accepted = _submit(client, identity, expense, body, key)
    assert accepted.status_code == 200, accepted.text
    assert _submit(client, identity, expense, body, key).json()["confirmation_receipt"] == accepted.json()["confirmation_receipt"]
    assert client.get("/api/funds/accounts/" + account["public_id"], headers=identity.app_headers).json()["balance_minor"] == 97067
