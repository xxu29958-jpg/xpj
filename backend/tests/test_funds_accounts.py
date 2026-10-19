"""One real PostgreSQL journey owns the purchase/funds/credit invariant."""
import json
import re
from dataclasses import replace
from datetime import date, timedelta
from html import unescape
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import AccountMovement, CreditFacility, Debt, Expense, ExpenseFunding, Repayment
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms


def test_existing_debt_becomes_one_credit_account_without_rewriting_history(client, identity):
    from app.services.debt_service._fold import compute_remaining_as_of
    from app.services.time_service import now_utc
    from tests.debt_repayment_goal_helpers import _create_external_debt, _repay_debt

    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    url = f"/api/debts/{debt['public_id']}"
    before = now_utc()
    _repay_debt(client, identity.app_headers, debt, amount_cents=3000)
    after_payment = now_utc()
    current = client.get(url, headers=identity.app_headers).json()
    choices = client.get("/api/funds/accounts/existing-debts/list", headers=identity.app_headers).json()
    assert choices[0]["remaining_home_minor"] == 7000
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    body = {"name": "原信用卡", "kind": "credit", "currency_code": "CNY", "opening_amount_minor": 6800,
        "opening_date": choices[0]["earliest_opening_date"], "opening_source": "平台核对为68元；原记录存在2元差异", "visibility": "ledger",
        "existing_debt": {"public_id": debt["public_id"], "expected_row_version": debt["row_version"]}}
    stale = client.post("/api/funds/accounts", headers=headers, json=body)
    assert stale.status_code == 409 and stale.json()["error"] == "state_conflict"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CreditFacility)) == 0
    body["existing_debt"]["expected_row_version"] = current["row_version"]
    headers["Idempotency-Key"] = str(uuid4())
    saved = client.post("/api/funds/accounts", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["debt_public_id"] == debt["public_id"] and saved.json()["balance_minor"] == -6800
    assert client.post("/api/funds/accounts", headers=headers, json=body).json() == saved.json()
    with SessionLocal() as db:
        from app.services.debt_service import count_open_external_debts
        assert count_open_external_debts(db, ["owner"]) == {"owner": 1}
        original = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert original.principal_amount_cents == 10000
        assert compute_remaining_as_of(db, original, before) == 10000
        assert compute_remaining_as_of(db, original, after_payment) == 7000
        assert compute_remaining_as_of(db, original, now_utc()) == 6800
        adopted = db.scalar(select(CreditFacility))
        assert adopted.adopted_from["remaining_home_minor"] == 7000
        assert adopted.adopted_from["opening_amount_minor"] == 6800
    current = client.get(url, headers=identity.app_headers).json()
    assert current["remaining_amount_cents"] == 6800 and current["paid_amount_cents"] == 3000
    for path, payload in (("/kind", {"debt_kind": "one_off"}), ("/repayments", {"amount_cents": 100})):
        refused = client.post(url + path, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={**payload, "expected_row_version": current["row_version"]})
        assert refused.status_code == 409 and refused.json()["error"] == "credit_account_required"
    assert client.get("/api/funds/accounts/existing-debts/list", headers=identity.app_headers).json() == []
    _correct_adopted_payment(client, identity, saved.json(), debt, after_payment)
    prepaid = _create_funds_account(client, identity, "信用卡多存余额", "credit", -500)
    assert prepaid["balance_minor"] == 500
    with SessionLocal() as db:
        prepaid_debt = db.scalar(select(Debt).where(Debt.public_id == prepaid["debt_public_id"]))
        assert prepaid_debt.status == "cleared"
        assert count_open_external_debts(db, ["owner"]) == {"owner": 1}


def _correct_adopted_payment(client, identity, account, original_debt, historical_time):
    from app.models import AccountBalanceObservation, RepaymentVoid
    from app.services.debt_service._fold import compute_remaining_as_of
    account_url = "/api/funds/accounts/" + account["public_id"]
    prior = client.get(account_url, headers=identity.app_headers).json()["prior_repayments"]
    assert prior["items"][0]["amount_cents"] == 3000
    body = {"expected_row_version": account["row_version"], "repayment_public_id": prior["items"][0]["public_id"],
        "occurred_on": account["opening_date"], "reason": "旧30元还款未发生，平台核对当前欠款98元"}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    refused = client.post(account_url + "/repayments/void", headers=headers, json=body)
    assert refused.status_code == 422 and refused.json()["error"] == "balance_review_required"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RepaymentVoid)) == 0
    body["reviewed_balance_minor"] = -9800
    headers["Idempotency-Key"] = str(uuid4())
    corrected = client.post(account_url + "/repayments/void", headers=headers, json=body)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["balance_minor"] == -9800
    assert client.get(account_url, headers=identity.app_headers).json()["prior_repayments"]["items"][0]["status"] == "voided"
    assert client.post(account_url + "/repayments/void", headers=headers, json=body).json() == corrected.json()
    debt = client.get("/api/debts/" + original_debt["public_id"], headers=identity.app_headers).json()
    assert (debt["remaining_amount_cents"], debt["paid_amount_cents"]) == (9800, 0)
    with SessionLocal() as db:
        original = db.scalar(select(Debt).where(Debt.public_id == original_debt["public_id"]))
        assert compute_remaining_as_of(db, original, historical_time) == 7000
        assert (db.scalar(select(func.count()).select_from(Repayment)),
            db.scalar(select(func.count()).select_from(RepaymentVoid)),
            db.scalar(select(func.count()).select_from(AccountBalanceObservation))) == (1, 1, 1)
        assert list(db.scalars(select(AccountMovement.kind).order_by(AccountMovement.id))) == ["opening", "reconciliation"]


@pytest.mark.real_db  # The portable outlet owns a separate read-only snapshot connection.
def test_credit_purchases_and_bank_principal_share_one_financial_history(client, identity, monkeypatch):
    bank = _create_funds_account(client, identity, "工资卡 1234", "bank", 100000)
    templates = client.get("/api/funds/accounts/templates/list", headers=identity.app_headers)
    assert templates.status_code == 200, templates.text
    huabei = next(row for row in templates.json() if row["key"] == "huabei")
    credit = _create_funds_account(client, identity, huabei["name"], huabei["kind"], 0)
    unknown = _create_funds_account(client, identity, "待核对零钱", "wallet", None)
    assert unknown["balance_minor"] is None
    assert int(credit["balance_minor"]) == 0
    assert credit["credit_terms"]["available_credit_minor"] == 1500000
    assert credit["credit_terms"]["payment_due_day"] == 15
    purchase_ids = []
    for amount in (3790, 2000, 500):
        body = {"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": amount,
            "merchant": "实际购买", "category": "购物", "funding": [{"component_id": str(uuid4()),
            "account_public_id": credit["public_id"], "account_row_version": credit["row_version"],
            "expense_amount_minor": amount, "account_amount_minor": amount}]}
        response = client.post("/api/expenses/manual", headers=identity.app_headers, json=body)
        assert response.status_code == 200, response.text
        assert client.post("/api/expenses/manual", headers=identity.app_headers, json=body).json() == response.json()
        purchase_ids.append(response.json()["id"])
        credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    assert int(credit["balance_minor"]) == -6290
    funding = client.get(f"/api/expenses/{purchase_ids[0]}/funding", headers=identity.app_headers)
    assert funding.status_code == 200, funding.text
    assert funding.json()["total_minor"] == 3790
    assert funding.json()["parts"][0]["account_public_id"] == credit["public_id"]
    _save_reviewed_funding(client, identity, funding.json(), credit)
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    debts = client.get("/api/debts", headers=identity.app_headers)
    assert debts.status_code == 200, debts.text
    tracked = next(row for row in debts.json()["items"] if row["public_id"] == credit["debt_public_id"])
    assert int(tracked["remaining_amount_cents"]) == 6290
    captured = client.post("/api/repayment-drafts", headers=identity.app_headers,
        json={"source": "alipay", "original_currency": "CNY", "original_amount": "41.20",
            "merchant_label": "花呗还款含费用", "notification_key": str(uuid4())})
    assert captured.status_code == 201, captured.text
    draft_id = captured.json()["public_id"]
    payment = {"expected_row_version": credit["row_version"], "payer_public_id": bank["public_id"],
        "payer_row_version": bank["row_version"], "principal_minor": 4000, "payer_amount_minor": 4000,
        "occurred_on": date.today().isoformat(), "note": "实付本金", "calendar_revision": credit["calendar_revision"],
        "new_fee_minor": 120, "fee_note": "本次首次发生手续费", "source_repayment_draft_id": draft_id}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    url = "/api/funds/accounts/" + credit["public_id"] + "/repay"
    refused = client.post(url, headers=headers, json=payment)
    assert refused.status_code == 422 and refused.json()["error"] == "installment_allocation_required"
    assert client.get("/api/repayment-drafts/" + draft_id, headers=identity.app_headers).json()["status"] == "pending"
    draws = client.get("/api/funds/accounts/" + credit["public_id"] + "/installments", headers=identity.app_headers).json()["draws"]
    draw_ids = {int(row["original_minor"]): row["public_id"] for row in draws if int(row["original_minor"]) > 0}
    payment["draw_allocations"] = [{"draw_public_id": draw_ids[amount], "principal_minor": paid}
        for amount, paid in ((3790, 1500), (2000, 2000), (500, 500))]
    headers["Idempotency-Key"] = str(uuid4())
    result = client.post(url, headers=headers, json=payment)
    assert result.status_code == 200, result.text
    assert client.post(url, headers=headers, json=payment).json() == result.json()
    assert int(result.json()["balance_minor"]) == -2290
    resolved = client.get("/api/repayment-drafts/" + draft_id, headers=identity.app_headers).json()
    assert (resolved["status"], resolved["committed_debt_public_id"]) == ("confirmed", credit["debt_public_id"])
    repeated = client.post(url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json=payment)
    assert repeated.status_code == 409 and repeated.json()["error"] == "state_conflict"
    bank = client.get("/api/funds/accounts/" + bank["public_id"], headers=identity.app_headers).json()
    assert int(bank["balance_minor"]) == 95880
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(Expense.amount_cents)).where(Expense.id.in_(purchase_ids))) == 6290
        assert db.scalar(select(func.count()).select_from(CreditFacility)) == 1
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.voided_at.is_(None))) == 4
        assert db.scalar(select(func.count()).select_from(Repayment)) == 1
        assert db.scalar(select(func.count()).select_from(Debt)) == 1
        assert db.scalar(select(func.sum(Expense.amount_cents))) == 6410
    source = client.get(f"/api/expenses/{purchase_ids[0]}", headers=identity.app_headers).json()
    refund = {"kind": "refund", "original_amount_minor": 1000, "accounting_date": date.today().isoformat(),
        "reason": "实际抵扣未偿本金", "expected_row_version": source["row_version"], "destinations": [{
            "account_public_id": credit["public_id"], "account_row_version": result.json()["row_version"],
            "original_amount_minor": 1000, "received_amount_minor": 1000}]}
    refund_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    refunded = client.post(f"/api/expenses/{purchase_ids[0]}/offsets", json=refund, headers=refund_headers)
    assert refunded.status_code == 201, refunded.text
    assert client.post(f"/api/expenses/{purchase_ids[0]}/offsets", json=refund, headers=refund_headers).json() == refunded.json()
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    assert int(credit["balance_minor"]) == -1290
    draws = client.get("/api/funds/accounts/" + credit["public_id"] + "/installments", headers=identity.app_headers).json()["draws"]
    assert {row["public_id"]: int(row["remaining_minor"]) for row in draws}[draw_ids[3790]] == 1290
    overview = client.get("/api/funds/accounts/summary/net-worth", headers=identity.app_headers).json()
    assert (int(overview["assets_minor"]), int(overview["liabilities_minor"]), int(overview["net_worth_minor"])) == (95880, 1290, 94590)
    assert overview["unknown_accounts"] == 1

    _assert_purchase_rolls_back(client, identity, monkeypatch, credit)
    # Refunding an already partly settled purchase retains spare credit instead of settling an unrelated older purchase.
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    source = client.get(f"/api/expenses/{purchase_ids[0]}", headers=identity.app_headers).json()
    refund["original_amount_minor"], refund["expected_row_version"] = 2790, source["row_version"]
    refund["destinations"][0].update(account_row_version=credit["row_version"], original_amount_minor=2790, received_amount_minor=2790)
    extra = client.post(f"/api/expenses/{purchase_ids[0]}/offsets", json=refund,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())})
    assert extra.status_code == 201, extra.text
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    assert (credit["balance_minor"], credit["unallocated_credit_minor"]) == (1000, 1500)
    _apply_and_correct_spare_credit(client, identity, credit)
    debt = client.get("/api/debts/" + credit["debt_public_id"], headers=identity.app_headers)
    assert debt.status_code == 200, debt.text
    assert debt.json()["remaining_amount_cents"] == 0
    offset = next(row for row in extra.json()["active_offsets"] if row["original_amount_minor"] == 2790)
    voided = client.post(f"/api/expenses/{purchase_ids[0]}/offsets/{offset['public_id']}/voids",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"void_reason": "这笔退款已被撤回", "expected_row_version": offset["row_version"]})
    assert voided.status_code == 201, voided.text
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    assert credit["credit_applications"]["history"][0]["applied_minor"] == 0
    debt = client.get("/api/debts/" + credit["debt_public_id"], headers=identity.app_headers).json()
    assert debt["remaining_amount_cents"] == 1790

    _correct_captured_payment(client, identity, draft_id, resolved["correction_versions"], bank, credit)
    assert client.post(url, headers=headers, json=payment).json() == result.json()
    _export_funds_history(client, identity, bank, credit)


def _apply_and_correct_spare_credit(client, identity, credit):
    url = "/api/funds/accounts/" + credit["public_id"]
    options = credit["credit_applications"]
    source, target = options["credits"][0], options["obligations"][0]
    body = {"expected_row_version": credit["row_version"], "credit_public_id": source["public_id"],
        "draw_public_id": target["public_id"], "amount_minor": 500, "reason": "退款经平台确认抵扣另一笔购买"}
    with SessionLocal() as db:
        before = tuple(db.scalar(select(func.count()).select_from(model)) for model in (Expense, AccountMovement, Repayment))
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    applied = client.post(url + "/credit-applications", json=body, headers=headers)
    assert applied.status_code == 200, applied.text
    assert client.post(url + "/credit-applications", json=body, headers=headers).json() == applied.json()
    result = applied.json()
    assert (result["balance_minor"], result["unallocated_credit_minor"]) == (1000, 1000)
    review = client.get(url, headers=identity.app_headers).json()["credit_applications"]["history"][0]
    assert review["applied_minor"] == 500
    undone = client.post(url + "/credit-applications/void", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": result["row_version"], "review_public_id": review["public_id"], "reason": "核对材料有误，恢复待分配"})
    assert undone.status_code == 200, undone.text
    assert (undone.json()["balance_minor"], undone.json()["unallocated_credit_minor"]) == (1000, 1500)
    assert client.get(url, headers=identity.app_headers).json()["credit_applications"]["history"][0]["void_reason"] == "核对材料有误，恢复待分配"
    again = client.post(url + "/credit-applications", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={**body, "expected_row_version": undone.json()["row_version"], "reason": "再次核实抵扣，后续退款撤回也须恢复欠款"})
    assert again.status_code == 200 and again.json()["unallocated_credit_minor"] == 1000, again.text
    with SessionLocal() as db:
        assert tuple(db.scalar(select(func.count()).select_from(model)) for model in (Expense, AccountMovement, Repayment)) == before


def _assert_purchase_rolls_back(client, identity, monkeypatch, credit):
    # A failure after the expense insert must not publish the purchase alone.
    from app.services import expense_funding_service
    def interrupted(*args, **kwargs):
        raise RuntimeError("funds publication interrupted")
    retry_body = {"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 500,
        "merchant": "实际购买", "category": "购物", "funding": [{"component_id": str(uuid4()),
            "account_public_id": credit["public_id"], "account_row_version": credit["row_version"],
            "expense_amount_minor": 500, "account_amount_minor": 500}]}
    with SessionLocal() as db:
        before_failure = tuple(db.scalar(select(func.count()).select_from(model)) for model in (Expense, AccountMovement))
    with monkeypatch.context() as patch:
        patch.setattr(expense_funding_service, "movement", interrupted)
        with pytest.raises(RuntimeError, match="funds publication interrupted"):
            client.post("/api/expenses/manual", headers=identity.app_headers, json=retry_body)
    with SessionLocal() as db:
        assert tuple(db.scalar(select(func.count()).select_from(model)) for model in (Expense, AccountMovement)) == before_failure
    resumed = client.post("/api/expenses/manual", headers=identity.app_headers, json=retry_body)
    assert resumed.status_code == 200, resumed.text


def _export_records(client, headers):
    response = client.get("/api/exports/portable", headers=headers)
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        return {name.removeprefix("records/").removesuffix(".jsonl"):
            [json.loads(line) for line in archive.read(name).splitlines()]
            for name in archive.namelist() if name.startswith("records/")}


def _save_reviewed_funding(client, identity, funding, credit):
    reviewed = client.post(f"/api/expenses/{funding['expense_id']}/funding",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "expected_row_version": funding["expense_row_version"], "reason": "重新核对实际付款来源",
            "parts": [{"component_id": str(uuid4()), "account_public_id": credit["public_id"],
                "account_row_version": credit["row_version"], "expense_amount_minor": funding["total_minor"],
                "account_amount_minor": funding["total_minor"]}]})
    assert reviewed.status_code == 200, reviewed.text


def _export_funds_history(client, identity, bank, credit):
    from tests.debt_proposal_helpers import _member_headers, _mint_member_actor
    _prepare_exported_plans(client, identity, bank, credit)
    _, token = _mint_member_actor(role="viewer")
    member = _export_records(client, _member_headers(token))
    assert credit["debt_public_id"] not in {row["public_id"] for row in member["debts"]}
    assert member["credit_facilities"] == member["repayments"] == member["payment_captures"] == member["installment_agreements"] == member["credit_fee_obligations"] == member["credit_application_reviews"] == []
    assert [row["public_id"] for row in member["financial_accounts"]] == [bank["public_id"]]
    hidden = [row for row in member["expense_funding"] if row["account_redaction_reason"]]
    assert hidden and all(row["account_id"] is None and row["account_amount_minor"] is None for row in hidden)
    assert all(row["resource_id"] != credit["public_id"] for row in member["accepted_operations"])
    private_receipt = next(row for row in member["accepted_operations"] if row["operation"] == "save_expense_funding")
    assert private_receipt["response_body_redaction_reason"] == "private_funding_scope"
    assert "account_public_id" not in private_receipt["response_body"]["parts"][0]
    assert all(row["resource_type"] != "payment_capture" for row in member["accepted_operations"])
    owner = _export_records(client, identity.app_headers)
    _assert_owner_funds_export(owner, member, credit)


def _assert_owner_funds_export(owner, member, credit):
    _assert_exported_credit_facts(owner, credit)
    assert owner["payment_captures"][0]["kind"] == "expense"
    assert all(owner[name] for name in ("installment_agreements", "installment_periods", "installment_draws"))
    assert [(row["purpose"], row["allocated_minor"]) for row in owner["envelope_allocations"]] == [("savings", 1000)]
    assert owner["envelope_revisions"] == member["envelope_revisions"]
    assert {"envelope_book", "payment_capture"} <= {row["resource_type"] for row in owner["accepted_operations"]}
    original = next(row for row in owner["accepted_operations"] if row["operation"] == "save_expense_funding")
    assert original["response_body"]["parts"][0]["account_public_id"] == credit["public_id"]


def _assert_exported_credit_facts(owner, credit):
    assert credit["public_id"] in {row["public_id"] for row in owner["financial_accounts"]}
    assert all(owner[name] for name in ("credit_facilities", "credit_settlement_allocations", "repayment_voids"))
    assert owner["repayments"][0]["settlement_kind"] == "credit"
    assert sorted((row["amount_minor"], row["voided_at"] is not None) for row in owner["credit_application_reviews"]) == [(500, False), (500, True)]
    assert sum(row["amount_minor"] for row in owner["account_movements"]
        if row["account_id"] == next(a["id"] for a in owner["financial_accounts"] if a["public_id"] == credit["public_id"])) == -5990
    fee = owner["credit_fee_obligations"][0]
    assert next(row for row in owner["expenses"] if row["id"] == fee["expense_id"])["original_amount_minor"] == 200
    assert fee["account_id"] in {row["id"] for row in owner["financial_accounts"]}


def _prepare_exported_plans(client, identity, bank, credit):
    headers = identity.app_headers
    bank_url = "/api/funds/accounts/" + bank["public_id"]
    bank = client.get(bank_url, headers=headers).json()
    shared = client.patch(bank_url, headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": bank["row_version"], "name": bank["name"], "visibility": "ledger"})
    assert shared.status_code == 200, shared.text
    bank = shared.json()
    saved = client.put("/api/budget/envelopes/" + date.today().strftime("%Y-%m"),
        headers={**headers, "Idempotency-Key": str(uuid4())}, json={"expected_row_version": 0,
            "home_currency_code": "CNY", "account_public_ids": [bank["public_id"]],
            "account_row_versions": {bank["public_id"]: bank["row_version"]},
            "allocations": {"savings": 1000}, "reason": "已确认的储蓄用途"})
    assert saved.status_code == 200, saved.text
    path = "/api/funds/accounts/" + credit["public_id"] + "/installments"
    source = client.get(path, headers=headers).json()
    draw = next(row for row in source["draws"] if row["remaining_minor"] > 0)
    agreed = client.post(path, headers={**headers, "Idempotency-Key": str(uuid4())}, json={
        "expected_row_version": source["account_row_version"], "name": "实际剩余一期", "source": "对账单核对",
        "agreed_on": str(date.today()), "draw_public_ids": [draw["public_id"]], "periods": [{
            "due_on": str(date.today()+timedelta(days=20)), "principal_minor": draw["remaining_minor"], "planned_fee_minor": 0}]})
    assert agreed.status_code == 200, agreed.text
    account = agreed.json()
    fee = client.post("/api/funds/accounts/" + credit["public_id"] + "/fees",
        headers={**headers, "Idempotency-Key": str(uuid4())}, json={
            "expected_row_version": account["row_version"], "calendar_revision": account["calendar_revision"],
            "occurred_on": str(date.today()), "amount_minor": 200, "note": "已入账尚未付款的利息"})
    assert fee.status_code == 200, fee.text


def _create_funds_account(client, identity, name, kind, opening, *, visibility="private", opening_date=None):
    result = client.post("/api/funds/accounts", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"name": name, "kind": kind, "currency_code": "CNY", "opening_amount_minor": opening,
            "opening_date": (opening_date or date.today()).isoformat(), "opening_source": "已核对对账单", "visibility": visibility,
            "credit_terms": {"credit_limit_minor": 2000000, "available_credit_minor": 1500000,
                "observed_on": str(date.today()), "source": "平台页面", "statement_day": 2, "payment_due_day": 15} if kind == "credit" else None})
    assert result.status_code == 200, result.text
    return result.json()


def test_same_owner_keeps_personal_and_family_funds_in_the_selected_ledger(client, identity):
    personal = _create_funds_account(client, identity, "个人工资卡", "bank", 10000)
    family = _create_funds_account(client, replace(identity, app_token=identity.tenant_app_token),
        "家庭生活费", "bank", 20000, visibility="ledger")
    for headers, local, foreign in ((identity.app_headers, personal, family),
            (identity.gray_app_headers, family, personal)):
        listing = client.get("/api/funds/accounts", headers=headers).json()
        assert [row["public_id"] for row in listing] == [local["public_id"]]
        overview = client.get("/api/funds/accounts/summary/net-worth", headers=headers).json()
        assert overview["assets_minor"] == local["balance_minor"]
        foreign_url = "/api/funds/accounts/" + foreign["public_id"]
        assert client.get(foreign_url, headers=headers).status_code == 404
        body = {"expected_row_version": foreign["row_version"], "kind": "income", "amount_minor": 1000,
            "occurred_on": date.today().isoformat(), "note": "不能写入其他账本", "calendar_revision": foreign["calendar_revision"]}
        refused = client.post(foreign_url + "/activities", headers={**headers, "Idempotency-Key": str(uuid4())}, json=body)
        assert refused.status_code == 404, refused.text
        local_url = "/api/funds/accounts/" + local["public_id"]
        transfer = {**body, "expected_row_version": local["row_version"], "kind": "transfer",
            "other_account_public_id": foreign["public_id"], "other_account_row_version": foreign["row_version"],
            "other_amount_minor": 1000}
        assert client.post(local_url + "/activities", headers={**headers, "Idempotency-Key": str(uuid4())},
            json=transfer).status_code == 404
        purchase = {"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1000,
            "merchant": "不能扣其他账本的资金", "category": "购物", "funding": [{"component_id": str(uuid4()),
            "account_public_id": foreign["public_id"], "account_row_version": foreign["row_version"],
            "expense_amount_minor": 1000, "account_amount_minor": 1000}]}
        assert client.post("/api/expenses/manual", headers=headers, json=purchase).status_code == 404
        assert client.get(local_url, headers=headers).json()["balance_minor"] == local["balance_minor"]
        accepted_headers = {**headers, "Idempotency-Key": str(uuid4())}
        accepted_body = {**body, "expected_row_version": local["row_version"], "note": "本账本实际收入"}
        saved = client.post(local_url + "/activities", headers=accepted_headers, json=accepted_body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["balance_minor"] == local["balance_minor"] + 1000
        assert client.post(local_url + "/activities", headers=accepted_headers, json=accepted_body).json() == saved.json()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0
        assert list(db.scalars(select(AccountMovement.kind).order_by(AccountMovement.id))) == ["opening", "opening", "income", "income"]


def test_cash_envelopes_reserve_unsettled_purchases_without_spending_principal_twice(client, identity):
    bank = _create_funds_account(client, identity, "共同生活费", "bank", 100000, visibility="ledger",
        opening_date=date.today().replace(day=1) - timedelta(days=1))
    credit = _create_funds_account(client, identity, "花呗", "credit", 0)
    month = date.today().strftime("%Y-%m")
    url = "/api/budget/envelopes/" + month
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    body = {"expected_row_version": 0, "home_currency_code": "CNY", "account_public_ids": [bank["public_id"]],
        "account_row_versions": {bank["public_id"]: bank["row_version"]},
        "allocations": {"spending": 30000, "savings": 20000, "buffer": 0}, "reason": "按现有现金分配用途"}
    funded = client.put(url, headers=headers, json=body)
    assert funded.status_code == 200, funded.text
    assert (funded.json()["cash_minor"], funded.json()["reserved_minor"], funded.json()["unassigned_minor"]) == (100000, 50000, 50000)
    assert funded.json()["receipt_revision"] == 1 and funded.json()["purposes"] == []
    assert all(row["planned_minor"] is None for row in client.get(url, headers=identity.app_headers).json()["purposes"])
    assert client.put(url, headers=headers, json=body).json() == funded.json()
    budget = client.put("/api/budgets/monthly/" + month,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"home_currency_code": "CNY", "expected_row_version": None, "total_amount_cents": 0})
    assert budget.status_code == 200, budget.text
    planned = client.get(url, headers=identity.app_headers).json()
    assert next(row for row in planned["purposes"] if row["purpose"] == "spending")["planned_minor"] == 0
    assert (planned["reserved_minor"], planned["unassigned_minor"]) == (50000, 50000)
    hidden = client.patch("/api/funds/accounts/" + bank["public_id"],
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": bank["row_version"], "name": bank["name"], "visibility": "private"})
    assert (hidden.status_code, hidden.json()["error"]) == (409, "fund_account_in_envelopes")
    history_url = "/api/budget/envelopes/history/list"
    history = client.get(history_url, headers=identity.app_headers).json()
    assert (history[0]["row_version"], history[0]["allocation_snapshot"]["allocations"]) == (1, body["allocations"])
    assert client.get(history_url + "?before_version=1", headers=identity.app_headers).json() == []
    future = (date.today().replace(day=28) + timedelta(days=4)).strftime("%Y-%m")
    refused = client.put("/api/budget/envelopes/" + future,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={**body,
            "expected_row_version": 1, "allocations": {"spending": 60000}})
    assert (refused.status_code, refused.json()["error"]) == (409, "envelope_cash_insufficient")
    purchase = client.post("/api/expenses/manual", headers=identity.app_headers,
        json={"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 10000,
            "merchant": "实际购买", "category": "购物", "funding": [{"component_id": str(uuid4()),
                "account_public_id": credit["public_id"], "account_row_version": credit["row_version"],
                "expense_amount_minor": 10000, "account_amount_minor": 10000}]})
    assert purchase.status_code == 200, purchase.text
    used = client.get(url, headers=identity.app_headers).json()
    spending = next(row for row in used["purposes"] if row["purpose"] == "spending")
    assert (spending["available_minor"], spending["unpaid_credit_minor"], used["reserved_minor"], used["unassigned_minor"]) == (20000, 10000, 50000, 50000)
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    draws = client.get("/api/funds/accounts/" + credit["public_id"] + "/installments", headers=identity.app_headers).json()["draws"]
    payment = client.post("/api/funds/accounts/" + credit["public_id"] + "/repay",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "expected_row_version": credit["row_version"], "calendar_revision": credit["calendar_revision"],
            "payer_public_id": bank["public_id"], "payer_row_version": bank["row_version"],
            "principal_minor": 10000, "payer_amount_minor": 10000, "occurred_on": date.today().isoformat(),
            "note": "用已留出的现金还款", "draw_allocations": [{"draw_public_id": draws[0]["public_id"], "principal_minor": 10000}]})
    assert payment.status_code == 200, payment.text
    paid = client.get(url, headers=identity.app_headers).json()
    spending = next(row for row in paid["purposes"] if row["purpose"] == "spending")
    assert (spending["available_minor"], spending["unpaid_credit_minor"], paid["cash_minor"], paid["reserved_minor"], paid["unassigned_minor"]) == (20000, 0, 90000, 40000, 50000)
    _envelope_unlinked_purchase(client, identity, url, bank)


def _envelope_unlinked_purchase(client, identity, url, bank):
    unknown = client.post("/api/expenses/manual", headers=identity.app_headers,
        json={"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 5000, "category": "购物"})
    assert unknown.status_code == 200, unknown.text
    pending = client.get(url, headers=identity.app_headers).json()
    spending = next(row for row in pending["purposes"] if row["purpose"] == "spending")
    assert (spending["available_minor"], spending["unlinked_minor"], pending["unassigned_minor"]) == (15000, 5000, 50000)
    bank = client.get("/api/funds/accounts/" + bank["public_id"], headers=identity.app_headers).json()
    linked = client.post(f"/api/expenses/{unknown.json()['id']}/funding",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
            "expected_row_version": unknown.json()["row_version"], "reason": "核对实际扣款卡",
            "parts": [{"component_id": str(uuid4()), "account_public_id": bank["public_id"],
                "account_row_version": bank["row_version"], "expense_amount_minor": 5000, "account_amount_minor": 5000}]})
    assert linked.status_code == 200, linked.text
    settled = client.get(url, headers=identity.app_headers).json()
    assert (settled["cash_minor"], settled["reserved_minor"], settled["unassigned_minor"]) == (85000, 35000, 50000)
    _correct_funded_purchase_date(client, identity, unknown.json()["id"], bank)


def _correct_funded_purchase_date(client, identity, expense_id, bank):
    from app.models import FinancialAccount
    from app.services.funds_query import account_balance

    prior_day = date.today().replace(day=1) - timedelta(days=1)
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    bank = client.get("/api/funds/accounts/" + bank["public_id"], headers=headers).json()
    body = {"expected_row_version": current["row_version"], "reason": "实际发生于上月，核对原付款",
        "time_input": {"precision": "date_only", "calendar_revision": bank["calendar_revision"],
            "user_local_date": str(prior_day)},
        "funding": [{"component_id": str(uuid4()), "account_public_id": bank["public_id"],
            "account_row_version": bank["row_version"], "expense_amount_minor": 5000, "account_amount_minor": 5000}]}
    path = f"/api/expenses/{expense_id}/corrections"
    corrected = client.post(path, headers=headers, json=body)
    assert corrected.status_code == 201, corrected.text
    assert client.post(path, headers=headers, json=body).json() == corrected.json()
    with SessionLocal() as db:
        account = db.scalar(select(FinancialAccount).where(FinancialAccount.public_id == bank["public_id"]))
        assert account_balance(db, account, cutoff=prior_day) == 95000
        assert account_balance(db, account) == 85000
        inverse = db.scalar(select(AccountMovement).where(AccountMovement.account_id == account.id,
            AccountMovement.reversal_of_id.is_not(None)))
        assert inverse.occurred_on == db.get(AccountMovement, inverse.reversal_of_id).occurred_on
    _reverse_and_restore_funding(client, identity, expense_id, bank)


def _reverse_and_restore_funding(client, identity, expense_id, bank):
    path, account_url = f"/api/expenses/{expense_id}", "/api/funds/accounts/" + bank["public_id"]
    source = client.get(path, headers=identity.app_headers).json()
    for invalid_day in (date.today() + timedelta(days=1), date.fromisoformat(bank["opening_date"]) - timedelta(days=1)):
        refused = client.post(path + "/offsets", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"kind": "reversal", "accounting_date": str(invalid_day), "reason": "核对资金日期范围",
                "expected_row_version": source["row_version"]})
        assert refused.status_code == 422 and refused.json()["error"] == "funds_date_outside_coverage", refused.text
        assert client.get(account_url, headers=identity.app_headers).json()["balance_minor"] == 85000
        assert client.get(path, headers=identity.app_headers).json()["row_version"] == source["row_version"]
    for _ in range(2):
        source = client.get(path, headers=identity.app_headers).json()
        reversed_result = client.post(path + "/offsets", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"kind": "reversal", "accounting_date": str(date.today()), "reason": "核对消费冲正",
                "expected_row_version": source["row_version"]})
        assert reversed_result.status_code == 201, reversed_result.text
        assert client.get(account_url, headers=identity.app_headers).json()["balance_minor"] == 90000
        offset = next(row for row in reversed_result.json()["active_offsets"] if row["kind"] == "reversal")
        offset_url = path + "/offsets/" + offset["public_id"]
        correction = {"expected_row_version": offset["row_version"], "original_amount_minor": None,
            "accounting_date": str(date.today()), "category": "购物", "offset_reason": "更正冲正说明",
            "correction_reason": "再次核对凭证"}
        if _ == 0:
            refused = client.post(offset_url + "/corrections", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
                json={**correction, "accounting_date": str(date.today() + timedelta(days=1))})
            assert refused.status_code == 422 and refused.json()["error"] == "funds_date_outside_coverage"
            assert client.get(account_url, headers=identity.app_headers).json()["balance_minor"] == 90000
        corrected = client.post(offset_url + "/corrections", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json=correction)
        assert corrected.status_code == 201, corrected.text
        assert client.get(account_url, headers=identity.app_headers).json()["balance_minor"] == 90000
        current = next(row for row in corrected.json()["active_offsets"] if row["public_id"] == offset["public_id"])
        headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
        body = {"expected_row_version": current["row_version"], "void_reason": "冲正判断有误，保留真实消费"}
        undone = client.post(offset_url + "/voids", headers=headers, json=body)
        assert undone.status_code == 201, undone.text
        assert client.post(offset_url + "/voids", headers=headers, json=body).json() == undone.json()
        assert client.get(account_url, headers=identity.app_headers).json()["balance_minor"] == 85000
        assert client.get(path + "/funding", headers=identity.app_headers).json()["total_minor"] == 5000
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(
            ExpenseFunding.expense_id == expense_id, ExpenseFunding.voided_at.is_(None))) == 1


def _correct_captured_payment(client, identity, draft_id, reviewed_versions, bank, credit):
    # Correcting the captured transaction restores both cash and principal; its
    # separately recorded fee must not survive as a second false expense.
    correction_url = "/api/repayment-drafts/" + draft_id + "/as-expense"
    correction = {"reason": "核对原交易后确认这是消费", "correction_versions": reviewed_versions,
        "expense_currency": "CNY", "expense_amount_minor": 3790}
    correction_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    stale = client.post(correction_url, headers=correction_headers, json=correction)
    assert stale.status_code == 409 and stale.json()["error"] == "state_conflict"
    fresh = client.get("/api/repayment-drafts/" + draft_id, headers=identity.app_headers).json()
    correction["correction_versions"] = fresh["correction_versions"]
    missing_money = {key: value for key, value in correction.items() if key not in {"expense_currency", "expense_amount_minor"}}
    assert client.post(correction_url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json=missing_money).status_code == 422
    correction_headers["Idempotency-Key"] = str(uuid4())
    corrected = client.post(correction_url, headers=correction_headers, json=correction)
    assert corrected.status_code == 200, corrected.text
    assert client.post(correction_url, headers=correction_headers, json=correction).json() == corrected.json()
    bank_now = client.get("/api/funds/accounts/" + bank["public_id"], headers=identity.app_headers).json()
    credit_now = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    assert bank_now["balance_minor"] == 100000 and credit_now["balance_minor"] == -5790
    corrected_expense = client.get(f"/api/expenses/{corrected.json()['expense_id']}", headers=identity.app_headers).json()
    assert corrected_expense["original_amount_minor"] == 3790 and corrected_expense["status"] == "pending"
    with SessionLocal() as db:
        from app.models import ExpenseOffsetFact, RepaymentVoid
        fee_id = int(next(iter(fresh["correction_versions"]["fee_expense_versions"])))
        assert db.scalar(select(ExpenseOffsetFact.kind).where(ExpenseOffsetFact.expense_id == fee_id,
            ExpenseOffsetFact.status == "active")) == "reversal"
        assert db.scalar(select(func.count()).select_from(RepaymentVoid)) == 1


@pytest.fixture()
def installed_funds_web():
    yield from installed_web_setup()


@pytest.mark.currency_binding_unbound
def test_native_funds_entry_keeps_private_accounts_and_consumes_actual_funding(installed_funds_web):
    installed = installed_funds_web
    token = _connect_local_session(installed, next_url="/web/funds")
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed.browser.get("/web/funds?task=create", headers={"Cookie": cookie})
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)["/web/funds/save"]
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000", "Accept": "application/json"}
    fields.update(name="浏览器信用账户", kind="credit", currency_code="CNY", opening_amount="0", visibility="private",
        opening_source="本人对账", occurred_on="2026-10-18", institution="", tail="1234")
    rejected = {**fields, "opening_amount": "金额待核对"}
    refused = installed.browser.post("/web/funds/save", data=rejected, headers=headers)
    assert refused.status_code == 422 and refused.json()["draft_result"] == "rejected"
    reviewed = installed.browser.post("/web/funds/save", data={**rejected, "review_latest": "1"}, headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    replacement = hidden_post_forms(reviewed.text)["/web/funds/save"]
    assert replacement["idempotency_key"] != fields["idempotency_key"]
    assert f'data-funds-prepared-from="{fields["idempotency_key"]}"' in reviewed.text
    assert "金额待核对" in reviewed.text
    fields["idempotency_key"] = replacement["idempotency_key"]
    first = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert first.status_code == 200, first.text
    receipt = first.json()["receipt"]
    assert receipt["balance_minor"] == 0
    assert installed.browser.post("/web/funds/save", data=fields, headers=headers).json() == first.json()
    assert installed.browser.post("/web/funds/save", data={**fields, "review_latest": "1"}, headers=headers).json() == first.json()
    changed = installed.browser.post("/web/funds/save", data={**fields, "opening_amount": "金额待核对", "review_latest": "1"}, headers=headers)
    assert changed.status_code == 422, changed.text
    page = installed.browser.get("/web/expenses/new", headers=headers)
    assert page.status_code == 200, page.text
    form = hidden_post_forms(page.text)["/web/expenses/new"]
    form.update(amount_major="12.34", currency_code="CNY", merchant="浏览器真实付款", category="购物", note="",
        funding_json=json.dumps([{"component_id": str(uuid4()), "account_public_id": receipt["public_id"],
            "account_row_version": receipt["row_version"], "account_currency": "CNY", "expense_currency": "CNY",
            "expense_amount": "12.34", "account_amount": "12.34"}]))
    saved = installed.browser.post("/web/expenses/new", data=form, headers=headers, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    detail = installed.browser.get(first.json()["next"], headers=headers)
    assert detail.status_code == 200 and "12.34" in detail.text and "浏览器真实付款" in detail.text
    with SessionLocal() as db:
        purchase = db.scalar(select(Expense).where(Expense.merchant == "浏览器真实付款"))
        assert purchase.amount_cents == 1234
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.expense_id == purchase.id)) == 1
        expense_id = purchase.id
    funding_url = f"/web/expenses/{expense_id}/funding"
    page = installed.browser.get(funding_url, headers=headers)
    assert page.status_code == 200, page.text
    revised = hidden_post_forms(page.text)[funding_url]
    assert json.loads(revised["funding_json"])[0]["expense_amount"] == "12.34"
    revised["reason"] = "按原账户重新核对"
    saved = installed.browser.post(funding_url, data=revised, headers=headers)
    assert saved.status_code == 200, saved.text
    assert installed.browser.post(funding_url, data={**revised, "review_latest": "1"}, headers=headers).json() == saved.json()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 1
        assert db.scalar(select(func.sum(AccountMovement.amount_minor))) == -1234
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.voided_at.is_(None))) == 1
    _confirm_pending_with_funding(installed, headers, receipt)
    _native_envelope_arrangement(installed, headers)
    _native_recorded_fee(installed, headers, receipt["public_id"])
    _native_prior_repayment(installed, headers, receipt["ledger_id"])


def _native_prior_repayment(installed, headers, ledger_id):
    from app.schemas import DebtCreateRequest, RepaymentCreateRequest
    from app.services.debt_service import create_debt, record_repayment
    from app.services.ledger_calendar_service import current_ledger_date
    with SessionLocal() as db:
        debt = create_debt(db, tenant_id=ledger_id, created_by_account_id=installed.installation_account_id,
            owner_account_id=installed.installation_account_id, payload=DebtCreateRequest(home_currency_code="CNY",
                direction="i_owe", counterparty_type="external", counterparty_label="接入前信用账本", principal_amount_cents=10000))
        recorded = record_repayment(db, tenant_id=ledger_id, public_id=debt.public_id,
            actor_account_id=installed.installation_account_id, idempotency_key=str(uuid4()),
            payload=RepaymentCreateRequest(amount_cents=3000, expected_row_version=debt.row_version), commit=True)
        debt_choice = f"{debt.public_id}|{debt.row_version}"
        repayment_id = recorded.repayment_public_id
        today = current_ledger_date(db, ledger_id=ledger_id).isoformat()
    page = installed.browser.get("/web/funds?task=create", headers=headers)
    fields = hidden_post_forms(page.text)["/web/funds/save"]
    fields.update(name="接管历史信用账户", kind="credit", currency_code="CNY", opening_amount="68", visibility="private",
        opening_source="已核对", occurred_on=today, existing_debt=debt_choice)
    saved = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert saved.status_code == 200, saved.text
    account_id = saved.json()["receipt"]["public_id"]
    detail = installed.browser.get(saved.json()["next"], headers=headers)
    assert "接入账户前的还款" in detail.text and repayment_id in detail.text
    page = installed.browser.get(f"/web/funds?task=void_repayment&account_id={account_id}&repayment_id={repayment_id}", headers=headers)
    assert page.status_code == 200 and 'name="reviewed_debt_amount"' in page.text, page.text
    fields = hidden_post_forms(page.text)["/web/funds/save"]
    fields.update(reviewed_debt_amount="98", note="核实原30元并未还款", occurred_on=today)
    corrected = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert corrected.status_code == 200, corrected.text
    result = corrected.json()["receipt"]
    assert result["balance_minor"] == -9800 and "prior_repayments" not in result
    assert installed.browser.post("/web/funds/save", data=fields, headers=headers).json() == corrected.json()
    assert "核实原30元并未还款" in installed.browser.get(corrected.json()["next"], headers=headers).text


def _native_envelope_arrangement(installed, headers):
    page = installed.browser.get("/web/funds?task=create", headers=headers)
    account = hidden_post_forms(page.text)["/web/funds/save"]
    account.update(name="信封生活费", kind="bank", currency_code="CNY", opening_amount="1000",
                   opening_source="银行余额已核对", visibility="private", institution="", tail="", occurred_on=date.today().isoformat())
    created = installed.browser.post("/web/funds/save", headers=headers, data=account)
    assert created.status_code == 200, created.text
    bank = _native_share_account(installed, headers, created.json()["receipt"])
    page = installed.browser.get("/web/envelopes", headers=headers)
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)["/web/envelopes/save"]
    fields.update(note="先留生活费和储蓄", **{"source:" + bank["public_id"]: "1",
        "allocation:spending": "300", "allocation:savings": "200", "allocation:buffer": "0"})
    saved = installed.browser.post("/web/envelopes/save", headers=headers, data=fields)
    assert saved.status_code == 200, saved.text
    assert saved.json()["receipt"]["unassigned_minor"] == 50000
    assert installed.browser.post("/web/envelopes/save", headers=headers, data=fields).json() == saved.json()
    stale = {**fields, "idempotency_key": str(uuid4()), "allocation:savings": "250"}
    rejected = installed.browser.post("/web/envelopes/save", headers=headers, data=stale)
    assert (rejected.status_code, rejected.json()["draft_result"]) == (409, "rejected")
    reviewed = installed.browser.post("/web/envelopes/save", headers=headers, data={**stale, "review_latest": "1"})
    assert reviewed.status_code == 200, reviewed.text
    original_key = stale["idempotency_key"]
    stale.update(hidden_post_forms(reviewed.text)["/web/envelopes/save"])
    assert stale["idempotency_key"] != original_key
    resumed = installed.browser.post("/web/envelopes/save", headers=headers, data=stale)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["receipt"]["unassigned_minor"] == 45000
    _native_activity_correction(installed, headers, bank["public_id"])


def _native_activity_correction(installed, headers, account_id):
    page = installed.browser.get(f"/web/funds?task=income&account_id={account_id}", headers=headers)
    fields = hidden_post_forms(page.text)["/web/funds/save"]
    fields.update(activity_amount="20", note="错误的额外收入", occurred_on=str(date.today()))
    saved = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert saved.status_code == 200, saved.text
    assert "movements" not in saved.json()["receipt"]
    # Navigate the actual read page; action identities belong to its authorized history.
    page = installed.browser.get(saved.json()["next"], headers=headers)
    href = next(unescape(href) for href in re.findall(r'<a[^>]*href="([^"]+)"', page.text) if "task=void_activity" in href)
    page = installed.browser.get(href, headers=headers)
    assert page.status_code == 200 and "错误的额外收入" in page.text, page.text
    values = hidden_post_forms(page.text)["/web/funds/save"]
    assert json.loads(values["activity_parts_json"])[0]["amount_minor"] == -2000
    values.update(note="银行确认并无此到账", occurred_on=str(date.today()))
    corrected = installed.browser.post("/web/funds/save", data=values, headers=headers)
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["receipt"]["balance_minor"] == 100000
    assert installed.browser.post("/web/funds/save", data=values, headers=headers).json() == corrected.json()
    history = installed.browser.get(corrected.json()["next"], headers=headers)
    assert "已撤销，原记录保留" in history.text and "银行确认并无此到账" in history.text


def _native_share_account(installed, headers, bank):
    page = installed.browser.get("/web/funds?task=edit&account_id=" + bank["public_id"], headers=headers)
    values = hidden_post_forms(page.text)["/web/funds/save"]
    values.update(name=bank["name"], institution="", tail="", archived="false", edit_visibility="ledger")
    shared = installed.browser.post("/web/funds/save", headers=headers, data=values)
    assert shared.status_code == 200, shared.text
    assert shared.json()["receipt"]["visibility"] == "ledger"
    assert installed.browser.post("/web/funds/save", headers=headers, data=values).json() == shared.json()
    return shared.json()["receipt"]


def _confirm_pending_with_funding(installed, headers, account):
    from datetime import UTC, datetime

    from app.services.expense_accounting_time_service import refresh_legacy_expense_time
    with SessionLocal() as db:
        pending = Expense(tenant_id=account["ledger_id"], merchant="通知待核对消费", category="购物",
            home_currency_code="CNY", original_currency_code="CNY", original_amount_minor=1995,
            amount_cents=1995, status="pending", source="notification", fx_status="ready",
            expense_time=datetime.now(UTC))
        refresh_legacy_expense_time(db, pending)
        db.add(pending)
        db.commit()
        expense_id = pending.id
    page = installed.browser.get(f"/web/expenses/{expense_id}/edit", headers=headers)
    assert page.status_code == 200, page.text
    action = f"/web/expenses/{expense_id}/confirm"
    values = hidden_post_forms(page.text)[f"/web/expenses/{expense_id}/save"]
    values.update(amount_yuan="19.95", original_currency="CNY", merchant="通知待核对消费", category="购物", note="", tags="",
        funding_json=json.dumps([{"component_id": str(uuid4()), "account_public_id": account["public_id"],
            "account_row_version": account["row_version"], "account_currency": "CNY", "expense_currency": "CNY",
            "expense_amount": "19.95", "account_amount": "19.95"}]))
    refused = installed.browser.post(action, data=values, headers=headers)
    assert refused.status_code == 409, refused.text
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).status == "pending"
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.expense_id == expense_id)) == 0
    reviewed = installed.browser.post(action, data={**values, "review_latest": "1"}, headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    values.update(hidden_post_forms(reviewed.text)[f"/web/expenses/{expense_id}/save"])
    saved = installed.browser.post(action, data=values, headers=headers)
    assert saved.status_code == 200, saved.text
    assert installed.browser.post(action, data=values, headers=headers).json() == saved.json()
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).status == "confirmed"
        assert db.scalar(select(func.count()).select_from(ExpenseFunding).where(ExpenseFunding.expense_id == expense_id)) == 1
        assert db.scalar(select(func.sum(AccountMovement.amount_minor))) == -3229


@pytest.mark.real_db  # Portable history reads an independently authorized committed snapshot.
def test_actual_installments_refund_revision_and_cash_movements(client, identity):
    def post(path, body, *, key=None, expected=None):
        response = client.post(path, json=body, headers={**identity.app_headers, "Idempotency-Key": key or str(uuid4())})
        assert response.is_success if expected is None else response.status_code == expected, response.text
        return response.json()

    def get(path):
        response = client.get(path, headers=identity.app_headers)
        assert response.status_code == 200, response.text
        return response.json()

    def account(name, kind, opening):
        return post("/api/funds/accounts", {"name": name, "kind": kind, "currency_code": "CNY", "opening_amount_minor": opening,
            "opening_date": str(date.today()), "opening_source": "本人对账", "visibility": "ledger" if kind == "credit" else "private"})

    bank, credit = account("付款卡", "bank", 100000), account("信用账户", "credit", 0)
    credit_url, bank_url = "/api/funds/accounts/" + credit["public_id"], "/api/funds/accounts/" + bank["public_id"]
    purchase = post("/api/expenses/manual", {"client_ref": str(uuid4()), "amount_cents": 10000, "home_currency_code": "CNY",
        "merchant": "分期原购买", "category": "购物", "funding": [{"component_id": str(uuid4()), "account_public_id": credit["public_id"],
            "account_row_version": credit["row_version"], "expense_amount_minor": 10000, "account_amount_minor": 10000}]})
    sources = get(credit_url + "/installments")
    agreement = {"expected_row_version": sources["account_row_version"], "name": "实际两期合约", "source": "平台确认单",
        "agreed_on": str(date.today()), "draw_public_ids": [sources["draws"][0]["public_id"]], "periods": [
            {"due_on": str(date.today()+timedelta(days=15)), "principal_minor": 3000, "planned_fee_minor": 50},
            {"due_on": str(date.today()+timedelta(days=45)), "principal_minor": 7000, "planned_fee_minor": 100}]}
    key = str(uuid4())
    accepted = post(credit_url + "/installments", agreement, key=key)
    assert post(credit_url + "/installments", agreement, key=key) == accepted
    assert accepted["balance_minor"] == -10000
    goal_body = {"name": "按实际分期还清", "goal_type": "debt_repayment", "debt_public_ids": [accepted["debt_public_id"]]}
    goal_key = str(uuid4())
    goal = post("/api/goals", goal_body, key=goal_key)
    goal_url = "/api/goals/" + goal["public_id"]
    assert goal["debt_repayment"]["projected_payoff_date"] == agreement["periods"][-1]["due_on"]
    schedule = get(credit_url + "/installments")["agreements"][0]
    first_payment = {"expected_row_version": accepted["row_version"], "calendar_revision": credit["calendar_revision"],
        "payer_public_id": bank["public_id"], "payer_row_version": bank["row_version"], "principal_minor": 1000, "payer_amount_minor": 1000,
        "occurred_on": str(date.today()), "note": "第一期部分实付", "new_fee_minor": 20, "fee_note": "本次发生的分期费用",
        "period_allocations": [{"period_public_id": schedule["periods"][0]["public_id"], "principal_minor": 1000, "fee_minor": 20}]}
    fee_only = {**first_payment, "principal_minor": 0, "payer_amount_minor": 0,
        "period_allocations": [{"period_public_id": schedule["periods"][0]["public_id"], "principal_minor": 0, "fee_minor": 20}]}
    fee_key = str(uuid4())
    fee_accepted = post(credit_url + "/repay", fee_only, key=fee_key)
    assert post(credit_url + "/repay", fee_only, key=fee_key) == fee_accepted
    assert fee_accepted["balance_minor"] == -10000 and get(bank_url)["balance_minor"] == 99980
    first_payment.update(expected_row_version=fee_accepted["row_version"], payer_row_version=get(bank_url)["row_version"],
        new_fee_minor=0, fee_note=None,
        period_allocations=[{"period_public_id": schedule["periods"][0]["public_id"], "principal_minor": 1000}])
    credit = post(credit_url + "/repay", first_payment)
    schedule = get(credit_url + "/installments")["agreements"][0]
    assert schedule["periods"][0]["paid_principal_minor"] == 1000
    assert schedule["periods"][0]["paid_fee_minor"] == 20 and not schedule["needs_review"]
    repayment = next(row for row in get(credit_url)["movements"] if row["can_void_repayment"])
    undo = {"expected_row_version": credit["row_version"], "repayment_public_id": repayment["repayment_public_id"],
        "occurred_on": str(date.today()), "reason": "本金记录重复，实际费用保留"}
    undo_key = str(uuid4())
    credit = post(credit_url + "/repayments/void", undo, key=undo_key)
    assert post(credit_url + "/repayments/void", undo, key=undo_key) == credit
    unpaid = get(credit_url + "/installments")["agreements"][0]
    assert credit["balance_minor"] == -10000 and get(bank_url)["balance_minor"] == 99980
    assert unpaid["periods"][0]["paid_principal_minor"] == 0
    assert unpaid["periods"][0]["paid_fee_minor"] == 20 and not unpaid["needs_review"]
    credit = post(credit_url + "/repay", {**first_payment, "expected_row_version": credit["row_version"],
        "payer_row_version": get(bank_url)["row_version"], "new_fee_minor": 0, "fee_note": None,
        "period_allocations": [{"period_public_id": schedule["periods"][0]["public_id"], "principal_minor": 1000}]})
    source = get(f"/api/expenses/{purchase['id']}")
    post(f"/api/expenses/{purchase['id']}/offsets", {"kind": "refund", "original_amount_minor": 1000,
        "accounting_date": str(date.today()), "reason": "部分实际退款", "expected_row_version": source["row_version"], "destinations": [
            {"account_public_id": credit["public_id"], "account_row_version": credit["row_version"], "original_amount_minor": 1000, "received_amount_minor": 1000}]})
    updated = get(credit_url + "/installments")
    assert updated["agreements"][0]["needs_review"]
    assert get(goal_url)["debt_repayment"]["projected_payoff_date"] is None
    revised = {**agreement, "expected_row_version": updated["account_row_version"], "supersedes_public_id": schedule["public_id"],
        "source": "退款后平台重排确认单", "periods": [{"due_on": str(date.today()+timedelta(days=20)), "principal_minor": 2500, "planned_fee_minor": 30},
            {"due_on": str(date.today()+timedelta(days=50)), "principal_minor": 5500, "planned_fee_minor": 100}]}
    credit = post(credit_url + "/installments", revised)
    history = get(credit_url + "/installments")["agreements"]
    assert len(history) == 2 and history[0]["active"] and not history[1]["active"]
    assert history[1]["periods"][0]["paid_fee_minor"] == 20 and not history[0]["needs_review"]
    assert get(goal_url)["debt_repayment"]["projected_payoff_date"] == revised["periods"][-1]["due_on"]
    credit = _settle_rescheduled_fees(post, get, credit_url, bank_url, credit, history[0], first_payment, goal_url)
    assert credit["balance_minor"] == 0
    assert get(goal_url)["debt_repayment"]["evaluation_state"] == "achieved"
    _hide_credit_goal_account(client, identity, credit_url, credit, goal, goal_body, goal_key)
    credit = get(credit_url)
    bank = get(bank_url)
    assert bank["balance_minor"] == 90850
    source = get(f"/api/expenses/{purchase['id']}")
    post(f"/api/expenses/{purchase['id']}/offsets", {"kind": "refund", "original_amount_minor": 500,
        "accounting_date": str(date.today()), "reason": "清偿后的实际退款", "expected_row_version": source["row_version"], "destinations": [
            {"account_public_id": credit["public_id"], "account_row_version": credit["row_version"], "original_amount_minor": 500, "received_amount_minor": 500}]})
    assert get(credit_url)["balance_minor"] == 500
    wallet = account("零钱", "wallet", None)
    activity = {"expected_row_version": bank["row_version"], "kind": "transfer", "amount_minor": 1000, "occurred_on": str(date.today()),
        "note": "本人账户间转账", "calendar_revision": bank["calendar_revision"], "other_account_public_id": wallet["public_id"],
        "other_account_row_version": wallet["row_version"], "other_amount_minor": 1000}
    bank = post(bank_url + "/activities", activity)
    wallet_url = "/api/funds/accounts/" + wallet["public_id"]
    wallet = get(wallet_url)
    assert bank["balance_minor"] == 89850 and wallet["balance_minor"] is None and wallet["recorded_change_minor"] == 1000
    wallet = post(wallet_url + "/activities", {"expected_row_version": wallet["row_version"], "kind": "reconciliation", "amount_minor": 1000,
        "occurred_on": str(date.today()), "note": "核对外部零钱余额", "calendar_revision": wallet["calendar_revision"], "apply_adjustment": True})
    assert wallet["balance_minor"] == 1000 and wallet["observation"]["difference_minor"] == 0
    wallet = post(wallet_url + "/activities", {"expected_row_version": wallet["row_version"], "kind": "loan", "amount_minor": 5000,
        "occurred_on": str(date.today()), "note": "借款真实到账", "calendar_revision": wallet["calendar_revision"], "loan_name": "固定本金贷款",
        "loan_currency_code": "CNY", "loan_principal_minor": 5000})
    assert wallet["balance_minor"] == 6000
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 4  # one purchase, one paid fee and two incurred fees; clearing them adds no Expense
        assert db.scalar(select(func.count()).select_from(Debt)) == 2  # one revolving facility and one loan
    summary = get("/api/funds/accounts/summary/net-worth")
    assert summary["net_worth_minor"] == 91350  # loan and transfer do not manufacture net assets
    _assert_consumption_consumers(client, identity)
    _correct_cash_events(post, get, bank_url, wallet_url)
    # A real native minor unit may round below one home unit; settling it still clears the debt.
    from decimal import Decimal

    from app.models import ExchangeRate
    from app.services.currency_binding_service import resolve_write_capability
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(ExchangeRate(tenant_id=credit["ledger_id"], home_currency_code="CNY", currency_code="IDR",
            rate_date=date.today(), rate_to_cny=Decimal("0.00045"), source="manual"))
        db.commit()
    native = {"currency_code": "IDR", "opening_amount_minor": 1, "opening_date": str(date.today()),
        "opening_source": "原币余额核对", "visibility": "private"}
    small_bank = post("/api/funds/accounts", {**native, "name": "原币付款账户", "kind": "bank"})
    small_credit = post("/api/funds/accounts", {**native, "name": "原币欠款", "kind": "credit"})
    small_result = post("/api/funds/accounts/" + small_credit["public_id"] + "/repay", {
        "expected_row_version": small_credit["row_version"], "calendar_revision": small_credit["calendar_revision"],
        "payer_public_id": small_bank["public_id"], "payer_row_version": small_bank["row_version"],
        "principal_minor": 1, "payer_amount_minor": 1, "occurred_on": str(date.today()), "note": "原币全额结清"})
    assert small_result["balance_minor"] == 0
    assert get("/api/funds/accounts/" + small_bank["public_id"])["balance_minor"] == 0
    with SessionLocal() as db:
        native_payment = db.scalar(select(Repayment).where(Repayment.original_currency_code == "IDR"))
        assert native_payment.original_amount_minor == 1 and native_payment.amount_cents == 0
    _replay_funds_after_account_visibility_change(client, identity, get(bank_url))


def _assert_consumption_consumers(client, identity):
    # Purchase 100.00 - actual refunds 15.00 + incurred fees 1.50.
    # Principal payments, internal transfers and the loan deposit add no consumption.
    month = date.today().strftime("%Y-%m")
    stats = client.get("/api/stats/monthly", params={"month": month}, headers=identity.app_headers)
    budget = client.get("/api/budgets/monthly", params={"month": month}, headers=identity.app_headers)
    goal = client.post("/api/goals", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"name": "同一消费口径", "month": month, "target_amount_cents": 10000, "home_currency_code": "CNY"})
    assert (stats.status_code, budget.status_code, goal.status_code) == (200, 200, 201)
    assert (stats.json()["total_amount_cents"], budget.json()["spent_amount_cents"], goal.json()["spent_amount_cents"]) == (8650, 8650, 8650)
    assert goal.json()["remaining_amount_cents"] == 1350


def _replay_funds_after_account_visibility_change(client, identity, account):
    from tests.debt_proposal_helpers import _member_headers, _mint_member_actor

    _, token = _mint_member_actor(ledger_id=account["ledger_id"])
    member = {**_member_headers(token), "Idempotency-Key": str(uuid4())}
    url = "/api/funds/accounts/" + account["public_id"]

    def share(current, visibility):
        response = client.patch(url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": current["row_version"], "name": current["name"], "visibility": visibility})
        assert response.status_code == 200, response.text
        return response.json()

    shared = share(account, "ledger")
    body = {"expected_row_version": shared["row_version"], "calendar_revision": shared["calendar_revision"],
        "kind": "income", "amount_minor": 100, "occurred_on": str(date.today()), "note": "家人已确认的共同收入"}
    accepted = client.post(url + "/activities", headers=member, json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["receipt_revision"] == 1
    assert not {"movements", "prior_repayments", "fee_obligations", "credit_applications"} & accepted.json().keys()
    purchase = client.post("/api/expenses/manual", headers=member, json={"client_ref": str(uuid4()),
        "home_currency_code": "CNY", "amount_cents": 100, "merchant": "家人实际消费", "category": "购物"}).json()
    funding_url = f"/api/expenses/{purchase['id']}/funding"
    funding_headers = {**member, "Idempotency-Key": str(uuid4())}
    funding_body = {"expected_row_version": purchase["row_version"], "reason": "核实实际共同付款",
        "parts": [{"component_id": str(uuid4()), "account_public_id": account["public_id"],
            "account_row_version": accepted.json()["row_version"], "expense_amount_minor": 100, "account_amount_minor": 100}]}
    funded = client.post(funding_url, headers=funding_headers, json=funding_body)
    assert funded.status_code == 200, funded.text
    hidden = share(client.get(url, headers=identity.app_headers).json(), "private")
    assert client.get(url, headers=member).status_code == 404
    replay = client.post(url + "/activities", headers=member, json=body)
    assert (replay.status_code, replay.json().get("error")) == (404, "fund_account_not_found")
    funding_replay = client.post(funding_url, headers=funding_headers, json=funding_body)
    assert funding_replay.status_code == 200, funding_replay.text
    redacted = funding_replay.json()
    assert (redacted["expense_id"], redacted["expense_row_version"], redacted["total_minor"]) == (
        funded.json()["expense_id"], funded.json()["expense_row_version"], funded.json()["total_minor"])
    assert redacted["can_edit"] is False
    assert all(redacted["parts"][0][name] is None for name in (
        "account_public_id", "account_row_version", "currency_code", "account_amount_minor"))
    assert redacted["parts"][0]["account_name"] == "其他成员的私人付款账户"
    assert client.get(url, headers=identity.app_headers).json()["balance_minor"] == account["balance_minor"]
    share(hidden, "ledger")
    assert client.post(url + "/activities", headers=member, json=body).json() == accepted.json()
    assert client.post(funding_url, headers=funding_headers, json=funding_body).json() == funded.json()
    assert client.get(url, headers=identity.app_headers).json()["balance_minor"] == account["balance_minor"]


def _hide_credit_goal_account(client, identity, account_url, account, goal, goal_body, goal_key):
    goal_url = "/api/goals/" + goal["public_id"]
    headers = {**identity.app_headers, "Idempotency-Key": goal_key}
    assert client.post("/api/goals", headers=headers, json=goal_body).json() == goal
    date_headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    date_body = {"expected_row_version": goal["row_version"], "target_date": str(date.today() + timedelta(days=60))}
    dated = client.post(goal_url + "/target-date", headers=date_headers, json=date_body)
    assert dated.status_code == 200, dated.text
    result = client.patch(account_url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": account["row_version"], "name": "不再共享的信用账户", "visibility": "private"})
    assert result.status_code == 200, result.text
    response = client.get(goal_url, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    evaluation = response.json()["debt_repayment"]
    link = evaluation["linked_debts"][0]
    assert link["status"] == "unavailable" and evaluation["needs_review"]
    assert link["remaining_amount_cents"] is None and link["principal_amount_cents"] is None
    assert link["counterparty_label"] is None and link["source_id"] is None
    choices = client.get("/api/debts?lens=goal_candidates", headers=identity.app_headers).json()
    assert account["debt_public_id"] not in {item["public_id"] for item in choices["items"]}
    for replay in [client.post("/api/goals", headers=headers, json=goal_body),
            client.post(goal_url + "/target-date", headers=date_headers, json=date_body)]:
        assert replay.status_code in {200, 201}, replay.text
        retained = replay.json()
        hidden = retained["debt_repayment"]["linked_debts"][0]
        assert hidden["counterparty_label"] is None and hidden["remaining_amount_cents"] is None
        assert hidden["principal_amount_cents"] is None and hidden["source_id"] is None
        assert retained["public_id"] == goal["public_id"] and retained["debt_repayment"]["needs_review"]
        assert retained["debt_repayment"]["projected_payoff_date"] is None
    exported = _export_records(client, identity.app_headers)
    receipts = [row for row in exported["accepted_operations"] if row["resource_id"] == goal["public_id"]]
    assert len(receipts) == 2
    for row in receipts:
        hidden = row["response_body"]["debt_repayment"]["linked_debts"][0]
        assert hidden["counterparty_label"] is None and hidden["remaining_amount_cents"] is None
        assert hidden["source_id"] is None and row["response_body_redaction_reason"] == "private_credit_scope"


def _activity_void_input(account, kind):
    original = next(row for row in account["movements"] if row["kind"] == kind and not row["voided"])
    return {"expected_row_version": account["row_version"], "event_public_id": original["event_public_id"],
        "account_row_versions": {part["account_public_id"]: part["account_row_version"] for part in original["correction_parts"]},
        "occurred_on": str(date.today()), "reason": "核对后撤销错误资金记录"}


def _correct_cash_events(post, get, bank_url, wallet_url):
    loan = next(row for row in get("/api/funds/accounts") if row["name"] == "固定本金贷款")
    loan_url = "/api/funds/accounts/" + loan["public_id"]
    wallet = get(wallet_url)
    original = _activity_void_input(wallet, "loan")
    loan = post(loan_url + "/repay", {"expected_row_version": loan["row_version"], "calendar_revision": loan["calendar_revision"],
        "payer_public_id": wallet["public_id"], "payer_row_version": wallet["row_version"], "principal_minor": 1000,
        "payer_amount_minor": 1000, "occurred_on": str(date.today()), "note": "到账后实际还款"})
    post(wallet_url + "/activities/void", {**original, "expected_row_version": get(wallet_url)["row_version"]}, expected=409)
    assert get(wallet_url)["balance_minor"] == 5000 and get(loan_url)["balance_minor"] == -4000
    undo = _activity_void_input(get(wallet_url), "loan")
    key = str(uuid4())
    corrected = post(wallet_url + "/activities/void", undo, key=key)
    assert corrected["balance_minor"] == 0 and post(wallet_url + "/activities/void", undo, key=key) == corrected
    assert get(loan_url)["balance_minor"] == 1000 and get(loan_url)["unallocated_credit_minor"] == 1000
    post(wallet_url + "/activities/void", {**undo, "expected_row_version": corrected["row_version"],
        "account_row_versions": {row["public_id"]: row["row_version"] for row in (corrected, get(loan_url))}}, expected=409)
    bank = post(bank_url + "/activities/void", _activity_void_input(get(bank_url), "transfer"))
    assert bank["balance_minor"] == 90850 and get(wallet_url)["balance_minor"] == -1000
    assert get("/api/funds/accounts/summary/net-worth")["net_worth_minor"] == 91350
    post(bank_url + "/activities", {"expected_row_version": bank["row_version"], "calendar_revision": bank["calendar_revision"],
        "kind": "income", "amount_minor": 2000, "occurred_on": str(date.today()), "note": "误记重复收入"})
    bank = post(bank_url + "/activities/void", _activity_void_input(get(bank_url), "income"))
    assert bank["balance_minor"] == 90850
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 4
        assert db.scalar(select(func.count()).select_from(Debt)) == 2


def _settle_rescheduled_fees(post, get, credit_url, bank_url, credit, schedule, original_payment, goal_url):
    from app.routes._web_installments import selected_installment_values
    from app.schemas.installment import InstallmentsView
    payment = {**original_payment, "expected_row_version": credit["row_version"], "payer_row_version": get(bank_url)["row_version"],
        "principal_minor": 8000, "payer_amount_minor": 8000, "new_fee_minor": 0, "fee_note": None,
        "note": "先清偿全部本金，费用仍按合约待付", "period_allocations": [
            {"period_public_id": row["public_id"], "principal_minor": row["principal_minor"]} for row in schedule["periods"]]}
    credit = post(credit_url + "/repay", payment)
    assert (credit["balance_minor"], get(bank_url)["balance_minor"]) == (0, 90980)
    evaluation = get(goal_url)["debt_repayment"]
    assert evaluation["evaluation_state"] == "in_progress"
    assert evaluation["linked_debts"][0]["remaining_amount_cents"] == 0
    assert evaluation["linked_debts"][0]["status"] == "open"
    assert "费用" in evaluation["linked_debts"][0]["completion_note"]
    candidates = get("/api/debts?lens=goal_candidates")["items"]
    assert next(row for row in candidates if row["public_id"] == credit["debt_public_id"])["status"] == "open"
    source = get(credit_url + "/installments")
    values = selected_installment_values(InstallmentsView.model_validate(source), schedule["public_id"], "CNY")
    assert [row["fee"] for row in json.loads(values["periods_json"])] == ["0.30", "1.00"]
    revision = {"expected_row_version": credit["row_version"], "supersedes_public_id": schedule["public_id"],
        "name": schedule["name"], "source": "平台确认本金结清后仅余费用排期", "agreed_on": str(date.today()),
        "draw_public_ids": json.loads(values["draw_ids_json"]), "periods": [
            {"due_on": row["due_on"], "principal_minor": 0, "planned_fee_minor": row["planned_fee_minor"]}
            for row in schedule["periods"]]}
    key = str(uuid4())
    credit = post(credit_url + "/installments", revision, key=key)
    assert post(credit_url + "/installments", revision, key=key) == credit
    current = get(credit_url + "/installments")["agreements"][0]
    assert not current["needs_review"] and get(bank_url)["balance_minor"] == 90980
    for period in current["periods"]:
        key = str(uuid4())
        fee = {"expected_row_version": credit["row_version"], "calendar_revision": credit["calendar_revision"],
            "amount_minor": period["planned_fee_minor"], "period_public_id": period["public_id"],
            "occurred_on": str(date.today()), "note": "账单已产生费用，本次未支付"}
        credit = post(credit_url + "/fees", fee, key=key)
        assert post(credit_url + "/fees", fee, key=key) == credit
        expense_id = next(row["expense_id"] for row in get(credit_url)["fee_obligations"] if row["period_public_id"] == period["public_id"])
        history = get(f"/api/expenses/{expense_id}/revisions")
        assert history["items"][0]["after"]["funding"][0]["expense_amount_minor"] == fee["amount_minor"]
    assert credit["balance_minor"] == -130 and get(bank_url)["balance_minor"] == 90980
    current = get(credit_url + "/installments")["agreements"][0]
    assert all(row["unincurred_fee_minor"] == 0 and row["paid_fee_minor"] == 0 for row in current["periods"])
    legacy = {**payment, "expected_row_version": credit["row_version"], "payer_row_version": get(bank_url)["row_version"],
        "principal_minor": 130, "payer_amount_minor": 130, "period_allocations": []}
    post(credit_url + "/repay", legacy, expected=422)  # old clients cannot reinterpret fees as principal
    return _pay_and_correct_recorded_fees(post, get, credit_url, bank_url, credit, legacy)


def _pay_and_correct_recorded_fees(post, get, credit_url, bank_url, credit, payment):
    facts = get(credit_url)["fee_obligations"]
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(Expense))
    body = {**payment, "principal_minor": 0, "payer_amount_minor": 0, "payer_fee_amount_minor": 130,
        "fee_payments": [{"expense_id": row["expense_id"], "amount_minor": row["remaining_minor"]} for row in facts]}
    key = str(uuid4())
    credit = post(credit_url + "/repay", body, key=key)
    assert post(credit_url + "/repay", body, key=key) == credit
    detail = get(credit_url)
    assert detail["balance_minor"] == 0 and get(bank_url)["balance_minor"] == 90850
    assert all(fee["remaining_minor"] == 0 for fee in detail["fee_obligations"])
    paid = get(credit_url + "/installments")["agreements"][0]["periods"]
    assert [p["paid_fee_minor"] for p in paid] == [30, 100]
    original = next(row for row in detail["movements"] if row["can_void_repayment"])
    credit = post(credit_url + "/repayments/void", {"expected_row_version": credit["row_version"],
        "repayment_public_id": original["repayment_public_id"], "occurred_on": str(date.today()), "reason": "扣款尚未成功，撤销付款保留已记费用"})
    assert credit["balance_minor"] == -130 and get(bank_url)["balance_minor"] == 90980
    assert sum(row["paid_fee_minor"] for row in get(credit_url + "/installments")["agreements"][0]["periods"]) == 0
    credit = post(credit_url + "/repay", {**body, "expected_row_version": credit["row_version"], "payer_row_version": get(bank_url)["row_version"]})
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == before
    return credit


def _native_recorded_fee(installed, headers, account_id):
    page = installed.browser.get("/web/funds?task=incur_fee&account_id=" + account_id, headers=headers)
    assert page.status_code == 200, page.text
    values = hidden_post_forms(page.text)["/web/funds/save"]
    values.update(activity_amount="3.33", note="银行确认本期已产生利息", occurred_on=str(date.today()), fee_period_id="")
    result = installed.browser.post("/web/funds/save", data=values, headers=headers)
    assert result.status_code == 200, result.text
    assert installed.browser.post("/web/funds/save", data=values, headers=headers).json() == result.json()
    detail = installed.browser.get(result.json()["next"], headers=headers)
    assert detail.status_code == 200 and "银行确认本期已产生利息" in detail.text
    page = installed.browser.get("/web/funds?task=repay&account_id=" + account_id, headers=headers)
    assert page.status_code == 200 and "清偿已记费用" in page.text and "3.33" in page.text
    with SessionLocal() as db:
        fees = list(db.scalars(select(Expense).where(Expense.note == "银行确认本期已产生利息")))
        assert len(fees) == 1 and fees[0].original_amount_minor == 333
