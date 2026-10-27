"""Completed financial commands own goal achievement, including composite corrections."""
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.errors import AppError
from app.services import goal_debt_repayment_achievement
from tests.debt_repayment_goal_helpers import (
    _clear_debt,
    _create_debt_goal,
    _create_external_debt,
    _goal_latch_state,
)
from tests.test_funds_accounts import _create_funds_account


def _post(client, identity, path, body, *, key=None, status=201):
    result = client.post(path, headers={**identity.app_headers, "Idempotency-Key": key or str(uuid4())}, json=body)
    assert result.status_code == status, result.text
    return result.json()


def _get(client, identity, path):
    result = client.get(path, headers=identity.app_headers)
    assert result.status_code == 200, result.text
    return result.json()


def _funded_purchase(client, identity, credit, amount=10000):
    return _post(client, identity, "/api/expenses/manual", {"client_ref": str(uuid4()),
        "home_currency_code": "CNY", "amount_cents": amount, "category": "购物", "merchant": "原消费",
        "funding": [{"component_id": "purchase", "account_public_id": credit["public_id"],
            "account_row_version": credit["row_version"], "expense_amount_minor": amount, "account_amount_minor": amount}]}, status=200)


def test_correction_does_not_latch_temporary_zero_and_offset_latch_is_atomic(client, identity, monkeypatch):
    credit = _create_funds_account(client, identity, "信用付款", "credit", 0, visibility="ledger")
    purchase = _funded_purchase(client, identity, credit)
    goal = _create_debt_goal(client, identity.app_headers, name="真实结清",
        debt_public_ids=[credit["debt_public_id"]]).json()
    credit_url, expense_url = "/api/funds/accounts/" + credit["public_id"], f"/api/expenses/{purchase['id']}"
    credit = _get(client, identity, credit_url)
    corrected = _post(client, identity, expense_url + "/corrections", {
        "expected_row_version": purchase["row_version"], "reason": "原金额少记", "amount_cents": 20000,
        "funding": [{"component_id": "corrected", "account_public_id": credit["public_id"],
            "account_row_version": credit["row_version"], "expense_amount_minor": 20000, "account_amount_minor": 20000}]})
    assert _get(client, identity, credit_url)["balance_minor"] == -20000
    assert _goal_latch_state(goal["public_id"]) == (None, None)

    body = {"kind": "reversal", "accounting_date": str(date.today()), "reason": "误记消费",
        "expected_row_version": corrected["expense"]["row_version"]}
    key = str(uuid4())
    latch = goal_debt_repayment_achievement.stage_locked_goal_achievement

    def fail_after_latch(db, current):
        latch(db, current)
        assert current.achieved_version == 1
        raise AppError("state_conflict", status_code=409)

    with monkeypatch.context() as patch:
        patch.setattr(goal_debt_repayment_achievement, "stage_locked_goal_achievement", fail_after_latch)
        _post(client, identity, expense_url + "/offsets", body, key=key, status=409)
    assert _get(client, identity, credit_url)["balance_minor"] == -20000
    assert _goal_latch_state(goal["public_id"]) == (None, None)
    accepted = _post(client, identity, expense_url + "/offsets", body, key=key)
    achieved = _goal_latch_state(goal["public_id"])
    assert achieved[0] is not None and achieved[1] == 1
    assert _post(client, identity, expense_url + "/offsets", body, key=key) == accepted
    assert _goal_latch_state(goal["public_id"]) == achieved

    # Reopening before any goal GET preserves the already committed achievement.
    offset = accepted["active_offsets"][0]
    _post(client, identity, expense_url + "/offsets/" + offset["public_id"] + "/voids", {
        "expected_row_version": offset["row_version"], "void_reason": "恢复真实消费"})
    assert _get(client, identity, credit_url)["balance_minor"] == -20000
    assert _goal_latch_state(goal["public_id"]) == achieved
    assert _get(client, identity, "/api/goals/" + goal["public_id"])["debt_repayment"]["evaluation_state"] == "achieved"


def test_capture_restoration_does_not_require_an_old_replaced_funding_account(client, identity):
    from tests.debt_proposal_helpers import _member_headers, _mint_member_actor

    _, token = _mint_member_actor()
    member = SimpleNamespace(app_headers=_member_headers(token))
    old = _create_funds_account(client, member, "已经换走的来源", "credit", 0, visibility="ledger")
    current = _create_funds_account(client, identity, "真实消费来源", "credit", 0, visibility="ledger")
    purchase = _funded_purchase(client, identity, old)
    corrected = _post(client, identity, f"/api/expenses/{purchase['id']}/corrections", {
        "expected_row_version": purchase["row_version"], "reason": "核对实际付款卡", "funding": [
            {"component_id": "actual-card", "account_public_id": current["public_id"],
             "account_row_version": current["row_version"], "expense_amount_minor": 10000, "account_amount_minor": 10000}]})
    old_url = "/api/funds/accounts/" + old["public_id"]
    old = _get(client, member, old_url)
    hidden = client.patch(old_url, headers={**member.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": old["row_version"], "name": old["name"], "visibility": "private"})
    assert hidden.status_code == 200, hidden.text
    assert client.get(old_url, headers=identity.app_headers).status_code == 404

    manual = _create_external_debt(client, identity.app_headers)
    draft = _post(client, identity, f"/api/expenses/{purchase['id']}/repayment-draft", {
        "expected_row_version": corrected["expense"]["row_version"]})
    draft_url = "/api/repayment-drafts/" + draft["public_id"]
    _post(client, identity, draft_url + "/confirm", {"target_debt_public_id": manual["public_id"],
        "expected_row_version": manual["row_version"]})
    versions = _get(client, identity, draft_url)["correction_versions"]
    restored = _post(client, identity, draft_url + "/as-expense", {
        "reason": "应保留原消费", "correction_versions": versions}, status=200)
    assert restored["expense_id"] == purchase["id"]
    assert _get(client, identity, "/api/funds/accounts/" + current["public_id"])["balance_minor"] == -10000
    assert _get(client, member, old_url)["balance_minor"] == 0
    assert _get(client, identity, "/api/debts/" + manual["public_id"])["remaining_amount_cents"] == 10000


def test_resharing_credit_completes_goal_only_after_all_linked_debts_clear(client, identity):
    credit = _create_funds_account(client, identity, "共同目标信用卡", "credit", 10000, visibility="ledger")
    payer = _create_funds_account(client, identity, "实际付款", "bank", 10000)
    manual = _create_external_debt(client, identity.app_headers)
    goal = _create_debt_goal(client, identity.app_headers, name="全部还清",
        debt_public_ids=[manual["public_id"], credit["debt_public_id"]]).json()
    credit_url = "/api/funds/accounts/" + credit["public_id"]

    def visibility(value):
        account = _get(client, identity, credit_url)
        response = client.patch(credit_url, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
            json={"expected_row_version": account["row_version"], "name": account["name"], "visibility": value})
        assert response.status_code == 200, response.text
        return response.json()

    credit = visibility("private")
    _post(client, identity, credit_url + "/repay", {"expected_row_version": credit["row_version"],
        "calendar_revision": credit["calendar_revision"], "payer_public_id": payer["public_id"],
        "payer_row_version": payer["row_version"], "principal_minor": 10000, "payer_amount_minor": 10000,
        "occurred_on": str(date.today()), "note": "清偿信用卡"}, status=200)
    _clear_debt(client, identity.app_headers, manual)
    assert _goal_latch_state(goal["public_id"]) == (None, None)
    visibility("ledger")
    achieved = _goal_latch_state(goal["public_id"])
    assert achieved[0] is not None and achieved[1] == 1
