"""One real PostgreSQL journey owns the purchase/funds/credit invariant."""
import json
from datetime import date, timedelta
from uuid import uuid4

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
        "opening_date": str(date.today()), "opening_source": "平台核对为68元；原记录存在2元差异", "visibility": "ledger",
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


def test_credit_purchases_and_bank_principal_share_one_financial_history(client, identity, monkeypatch):
    def account(name, kind, opening):
        result = client.post("/api/funds/accounts", headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"name": name, "kind": kind, "currency_code": "CNY", "opening_amount_minor": opening,
                "opening_date": date.today().isoformat(), "opening_source": "已核对对账单", "visibility": "private",
                "credit_terms": {"credit_limit_minor": 2000000, "available_credit_minor": 1500000,
                    "observed_on": str(date.today()), "source": "平台页面", "statement_day": 2, "payment_due_day": 15} if kind == "credit" else None})
        assert result.status_code == 200, result.text
        return result.json()
    bank = account("工资卡 1234", "bank", 100000)
    credit = account("花呗", "credit", 0)
    unknown = account("待核对零钱", "wallet", None)
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
    debts = client.get("/api/debts", headers=identity.app_headers)
    assert debts.status_code == 200, debts.text
    tracked = next(row for row in debts.json()["items"] if row["public_id"] == credit["debt_public_id"])
    assert int(tracked["remaining_amount_cents"]) == 6290
    payment = {"expected_row_version": credit["row_version"], "payer_public_id": bank["public_id"],
        "payer_row_version": bank["row_version"], "principal_minor": 4000, "payer_amount_minor": 4000,
        "occurred_on": date.today().isoformat(), "note": "实付本金", "calendar_revision": credit["calendar_revision"],
        "new_fee_minor": 120, "fee_note": "本次首次发生手续费"}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    url = "/api/funds/accounts/" + credit["public_id"] + "/repay"
    refused = client.post(url, headers=headers, json=payment)
    assert refused.status_code == 422 and refused.json()["error"] == "installment_allocation_required"
    draws = client.get("/api/funds/accounts/" + credit["public_id"] + "/installments", headers=identity.app_headers).json()["draws"]
    draw_ids = {int(row["original_minor"]): row["public_id"] for row in draws if int(row["original_minor"]) > 0}
    payment["draw_allocations"] = [{"draw_public_id": draw_ids[amount], "principal_minor": paid}
        for amount, paid in ((3790, 1500), (2000, 2000), (500, 500))]
    headers["Idempotency-Key"] = str(uuid4())
    result = client.post(url, headers=headers, json=payment)
    assert result.status_code == 200, result.text
    assert client.post(url, headers=headers, json=payment).json() == result.json()
    assert int(result.json()["balance_minor"]) == -2290
    bank = client.get("/api/funds/accounts/" + bank["public_id"], headers=identity.app_headers).json()
    assert int(bank["balance_minor"]) == 95880
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(Expense.amount_cents)).where(Expense.id.in_(purchase_ids))) == 6290
        assert db.scalar(select(func.count()).select_from(CreditFacility)) == 1
        assert db.scalar(select(func.count()).select_from(ExpenseFunding)) == 4
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

    # A failure after the expense insert must not publish the purchase alone.
    from app.services import expense_funding_service
    def interrupted(*args, **kwargs):
        raise RuntimeError("funds publication interrupted")
    retry_body = {**body, "client_ref": str(uuid4()), "funding": [{**body["funding"][0],
        "component_id": str(uuid4()), "account_row_version": credit["row_version"]}]}
    import pytest
    with monkeypatch.context() as patch:
        patch.setattr(expense_funding_service, "movement", interrupted)
        with pytest.raises(RuntimeError, match="funds publication interrupted"):
            client.post("/api/expenses/manual", headers=identity.app_headers, json=retry_body)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 4
        assert db.scalar(select(func.count()).select_from(AccountMovement)) == 9
    resumed = client.post("/api/expenses/manual", headers=identity.app_headers, json=retry_body)
    assert resumed.status_code == 200, resumed.text
    # Refunding an already partly settled purchase retains spare credit instead of settling an unrelated older purchase.
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    source = client.get(f"/api/expenses/{purchase_ids[0]}", headers=identity.app_headers).json()
    refund["original_amount_minor"], refund["expected_row_version"] = 2790, source["row_version"]
    refund["destinations"][0].update(account_row_version=credit["row_version"], original_amount_minor=2790, received_amount_minor=2790)
    extra = client.post(f"/api/expenses/{purchase_ids[0]}/offsets", json=refund,
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())})
    assert extra.status_code == 201, extra.text
    credit = client.get("/api/funds/accounts/" + credit["public_id"], headers=identity.app_headers).json()
    assert credit["balance_minor"] == 1000 and credit["unallocated_credit_minor"] == 1500
    debt = client.get("/api/debts/" + credit["debt_public_id"], headers=identity.app_headers)
    assert debt.status_code == 200, debt.text
    assert debt.json()["remaining_amount_cents"] == 0
    offset = next(row for row in extra.json()["active_offsets"] if row["original_amount_minor"] == 2790)
    voided = client.post(f"/api/expenses/{purchase_ids[0]}/offsets/{offset['public_id']}/voids",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"void_reason": "这笔退款已被撤回", "expected_row_version": offset["row_version"]})
    assert voided.status_code == 201, voided.text
    debt = client.get("/api/debts/" + credit["debt_public_id"], headers=identity.app_headers).json()
    assert debt["remaining_amount_cents"] == 1790


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


def test_actual_installments_refund_revision_and_cash_movements(client, identity):
    def post(path, body, *, key=None):
        response = client.post(path, json=body, headers={**identity.app_headers, "Idempotency-Key": key or str(uuid4())})
        assert response.is_success, response.text
        return response.json()

    def get(path):
        response = client.get(path, headers=identity.app_headers)
        assert response.status_code == 200, response.text
        return response.json()

    def account(name, kind, opening):
        return post("/api/funds/accounts", {"name": name, "kind": kind, "currency_code": "CNY", "opening_amount_minor": opening,
            "opening_date": str(date.today()), "opening_source": "本人对账", "visibility": "private"})

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
    repayment = next(row for row in credit["movements"] if row["can_void_repayment"])
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
    revised = {**agreement, "expected_row_version": updated["account_row_version"], "supersedes_public_id": schedule["public_id"],
        "source": "退款后平台重排确认单", "periods": [{"due_on": str(date.today()+timedelta(days=20)), "principal_minor": 2500, "planned_fee_minor": 30},
            {"due_on": str(date.today()+timedelta(days=50)), "principal_minor": 5500, "planned_fee_minor": 100}]}
    credit = post(credit_url + "/installments", revised)
    history = get(credit_url + "/installments")["agreements"]
    assert len(history) == 2 and history[0]["active"] and not history[1]["active"]
    assert history[1]["periods"][0]["paid_fee_minor"] == 20 and not history[0]["needs_review"]
    bank = get(bank_url)
    final_payment = {**first_payment, "expected_row_version": credit["row_version"], "payer_row_version": bank["row_version"],
        "principal_minor": 8000, "payer_amount_minor": 8000, "new_fee_minor": 130, "fee_note": "修订合约实际费用", "note": "按修订合约提前清偿", "period_allocations": [
            {"period_public_id": row["public_id"], "principal_minor": row["principal_minor"], "fee_minor": row["planned_fee_minor"]} for row in history[0]["periods"]]}
    credit = post(credit_url + "/repay", final_payment)
    assert credit["balance_minor"] == 0
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
        assert db.scalar(select(func.count()).select_from(Expense)) == 3  # one purchase and two actually incurred fees
        assert db.scalar(select(func.count()).select_from(Debt)) == 2  # one revolving facility and one loan
    summary = get("/api/funds/accounts/summary/net-worth")
    assert summary["net_worth_minor"] == 91350  # loan and transfer do not manufacture net assets
    # A real native minor unit may round below one home unit; settling it still clears the debt.
    from decimal import Decimal

    from app.models import ExchangeRate
    with SessionLocal() as db:
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
