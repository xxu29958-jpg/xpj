"""Actual PostgreSQL/HTTP journeys, including the existing repayment workflow."""

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    BillSplitAgreementChange,
    BillSplitChangeProposal,
    BillSplitInvitation,
    Expense,
)
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client
from tests.bill_split_test_support import accept_split_http as _accept
from tests.bill_split_test_support import change_split_http as _change
from tests.bill_split_test_support import pay_member_http as _pay
from tests.bill_split_test_support import split_http as split_http
from tests.bill_split_test_support import split_versions as _versions
from tests.bill_split_test_support import split_view as _view
from tests.debt_proposal_helpers import _idem, _propose


def _financial_snapshot(client, split):
    view = _view(client, split["sender"], split["debt"])
    original = view["original_debt"]
    returned = view["return_debt"]
    with SessionLocal() as db:
        invitation = db.scalar(select(BillSplitInvitation).where(
            BillSplitInvitation.public_id == split["invitation"]))
        expense_amounts = (
            db.get(Expense, split["source"]).amount_cents,
            db.get(Expense, invitation.received_expense_id).amount_cents,
        )
        accepted_count = len(list(db.scalars(select(BillSplitAgreementChange))))
    debt_fields = ("principal_amount_cents", "paid_amount_cents", "remaining_amount_cents",
                   "status", "row_version", "is_forgiven")
    return {
        "agreement": (view["agreed_share_amount_cents"], view["settlement_net_amount_cents"]),
        "original": tuple(original[field] for field in debt_fields),
        "return": tuple(returned[field] for field in debt_fields) if returned else None,
        "expenses": expense_amounts,
        "accepted_count": accepted_count,
    }


def _browser(client, identity):
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, mint_session(client, identity=identity),
                        domain=PUBLIC_HOST, path="/")
    return browser


def _web_form(browser, split, *, command="create"):
    page = browser.get(
        f"/web/debts/{split['debt']}/split-agreement?ledger_id=owner&command={command}"
    )
    assert page.status_code == 200, page.text
    forms = hidden_post_forms(page.text)
    action, fields = next((action, fields) for action, fields in forms.items()
                          if action.startswith(f"/web/debts/{split['debt']}/split-changes"))
    assert fields["csrf_token"]
    return action, fields, page


def _post_web(browser, action, fields):
    return browser.post(action, data=fields, headers={"Origin": f"https://{PUBLIC_HOST}"})


def test_paid_share_refund_partial_return_and_changed_mind_preserve_actual_cash(client, split_http):
    split = split_http
    _pay(client, split["receiver"], split["sender"], split["debt"], 4_000)
    preview = client.get(f"/api/debts/{split['debt']}/split-agreement",
        headers=split["receiver"], params={"new_share_amount_cents": 2_000})
    assert preview.status_code == 200, preview.text
    assert preview.json()["preview"]["default_settlement_net_amount_cents"] == -2_000
    basis = _view(client, split["receiver"], split["debt"])
    proposal_request = {
        "headers": _idem(split["receiver"]),
        "json": {**_versions(basis), "new_share_amount_cents": 2_000,
                 "settlement_net_amount_cents": -2_000, "reason": "Review source refund"},
    }
    proposal_url = f"/api/debts/{split['debt']}/split-change-proposals"
    created = client.post(proposal_url, **proposal_request)
    assert created.status_code == 201, created.text
    proposal = created.json()
    headers = _idem(split["sender"])
    accepted = _accept(client, split, proposal, basis, headers=headers)
    assert accepted.status_code == 200, accepted.json()
    original_receipt = accepted.json()
    returned_id = original_receipt["return_debt"]["public_id"]
    payables = client.get("/api/debts?lens=payables", headers=split["sender"]).json()["items"]
    assert returned_id in [debt["public_id"] for debt in payables]
    _pay(client, split["sender"], split["receiver"], returned_id, 800)
    recreated = client.post(proposal_url, **proposal_request)
    assert recreated.status_code == 201, recreated.text
    assert recreated.json() == proposal
    replay = _accept(client, split, proposal, basis, headers=headers)
    assert replay.status_code == 200, replay.json()
    assert replay.json() == original_receipt
    next_proposal, next_basis = _change(client, split, share=3_000, net=-200)
    next_result = _accept(client, split, next_proposal, next_basis)
    assert next_result.status_code == 200, next_result.json()
    assert next_result.json()["return_debt"]["public_id"] == returned_id
    last_proposal, last_basis = _change(client, split, share=3_500, net=300)
    last = _accept(client, split, last_proposal, last_basis)
    assert last.status_code == 200, last.json()
    assert last.json()["original_debt"]["remaining_amount_cents"] == 300
    assert last.json()["return_debt"]["remaining_amount_cents"] == 0
    assert last.json()["original_paid_amount_cents"] == 4_000
    assert last.json()["return_paid_amount_cents"] == 800
    assert last.json()["original_debt"]["ledger_id"] is None
    with SessionLocal() as db:
        invitation = db.scalar(select(BillSplitInvitation).where(BillSplitInvitation.public_id == split["invitation"]))
        assert db.get(Expense, split["source"]).amount_cents == 10_000
        assert db.get(Expense, invitation.received_expense_id).amount_cents == 4_000
        assert len(list(db.scalars(select(BillSplitAgreementChange)))) == 3


def test_return_payment_pending_blocks_accept_and_confirming_it_invalidates_old_basis(client, split_http):
    split = split_http
    _pay(client, split["receiver"], split["sender"], split["debt"], 4_000)
    proposal, basis = _change(client, split, share=2_000, net=-2_000)
    result = _accept(client, split, proposal, basis)
    assert result.status_code == 200, result.json()
    returned = result.json()["return_debt"]
    next_proposal, next_basis = _change(client, split, share=3_000, net=-1_000)
    payment = _propose(client, split["sender"], returned["public_id"], proposed_amount_cents=800)
    assert payment.status_code == 201, payment.json()
    refused = _accept(client, split, next_proposal, next_basis)
    assert refused.status_code == 409
    assert refused.json()["error"] == "split_change_repayment_pending"
    confirmed = client.post(f"/api/debts/{returned['public_id']}/repayment-proposals/{payment.json()['public_id']}/confirm",
        headers=_idem(split["receiver"]), json={"expected_row_version": returned["row_version"]})
    assert confirmed.status_code == 201, confirmed.json()
    stale = _accept(client, split, next_proposal, next_basis)
    assert stale.status_code == 409
    assert stale.json()["error"] == "state_conflict"
    view = _view(client, split["receiver"], split["debt"])
    assert view["agreed_share_amount_cents"] == 2_000
    assert view["settlement_net_amount_cents"] == -1_200
    assert view["pending_proposal"]["public_id"] == next_proposal["public_id"]


@pytest.mark.parametrize("path", [
    "/api/debts/not-used/split-change-proposals",
    "/api/debts/not-used/split-change-proposals/not-used/accept",
    "/api/debts/not-used/split-change-proposals/not-used/reject",
    "/api/debts/not-used/split-change-proposals/not-used/withdraw",
])
@pytest.mark.parametrize("auth_headers", [{}, {"Authorization": "Bearer invalid-split-session"}])
def test_split_change_commands_require_valid_authentication(client, path, auth_headers):
    response = client.post(path, headers={**auth_headers, "Idempotency-Key": "split-auth-required"},
        json={"expected_row_version": 1, "expected_return_row_version": None,
              "new_share_amount_cents": 2_000, "settlement_net_amount_cents": 2_000,
              "reason": "must authenticate"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_api_reject_and_withdraw_record_the_right_actor_without_changing_financial_facts(
    client, split_http,
):
    split = split_http
    before = _financial_snapshot(client, split)

    rejected_proposal, _ = _change(client, split, share=3_000, net=3_000)
    reject_url = f"/api/debts/{split['debt']}/split-change-proposals/{rejected_proposal['public_id']}/reject"
    reject_headers = _idem(split["sender"])
    rejected = client.post(reject_url, headers=reject_headers)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    reject_replay = client.post(reject_url, headers=reject_headers)
    assert reject_replay.status_code == 200, reject_replay.text
    assert reject_replay.json() == rejected.json()

    withdrawn_proposal, _ = _change(client, split, share=3_500, net=3_500)
    withdraw_url = f"/api/debts/{split['debt']}/split-change-proposals/{withdrawn_proposal['public_id']}/withdraw"
    withdraw_headers = _idem(split["receiver"])
    withdrawn = client.post(withdraw_url, headers=withdraw_headers)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "withdrawn"
    withdraw_replay = client.post(withdraw_url, headers=withdraw_headers)
    assert withdraw_replay.status_code == 200, withdraw_replay.text
    assert withdraw_replay.json() == withdrawn.json()

    with SessionLocal() as db:
        rejected_row = db.scalar(select(BillSplitChangeProposal).where(
            BillSplitChangeProposal.public_id == rejected_proposal["public_id"]))
        withdrawn_row = db.scalar(select(BillSplitChangeProposal).where(
            BillSplitChangeProposal.public_id == withdrawn_proposal["public_id"]))
        assert rejected_row.resolved_by_account_id == split["sender_id"]
        assert withdrawn_row.resolved_by_account_id == split["receiver_id"]
    assert _financial_snapshot(client, split) == before


def test_real_web_split_change_routes_preserve_preview_and_replay_semantics(
    client, identity, split_http,
):
    split = split_http
    browser = _browser(client, identity)
    try:
        before_preview = _financial_snapshot(client, split)
        create_action, create_fields, _ = _web_form(browser, split)
        assert create_action == f"/web/debts/{split['debt']}/split-changes"
        create_fields.update(new_share_amount_major="30.00", settlement_net_amount_major="30.00",
                             reason="Web proposes a smaller share")
        preview = _post_web(
            browser,
            f"/web/debts/{split['debt']}/split-agreement/preview",
            create_fields,
        )
        assert preview.status_code == 200, preview.text
        assert "按新份额预览结算" in preview.text
        assert _financial_snapshot(client, split) == before_preview
        with SessionLocal() as db:
            assert db.scalar(select(BillSplitChangeProposal)) is None

        preview_action, preview_fields = next(
            (action, fields) for action, fields in hidden_post_forms(preview.text).items()
            if action.startswith(f"/web/debts/{split['debt']}/split-changes")
        )
        assert preview_action == create_action
        preview_fields.update(new_share_amount_major="30.00", settlement_net_amount_major="30.00",
                              reason="Web proposes a smaller share")
        created = _post_web(browser, preview_action, preview_fields)
        assert created.status_code == 200, created.text
        assert "这次约定操作已完成" in created.text
        with SessionLocal() as db:
            web_created = db.scalar(select(BillSplitChangeProposal).where(
                BillSplitChangeProposal.status == "pending"))
            assert web_created.proposed_by_account_id == split["sender_id"]
            web_created_id = web_created.public_id

        receiver_basis = _view(client, split["receiver"], split["debt"])
        accept_headers = _idem(split["receiver"])
        accepted = client.post(
            f"/api/debts/{split['debt']}/split-change-proposals/{web_created_id}/accept",
            headers=accept_headers, json=_versions(receiver_basis),
        )
        replay = client.post(
            f"/api/debts/{split['debt']}/split-change-proposals/{web_created_id}/accept",
            headers=accept_headers, json=_versions(receiver_basis),
        )
        assert accepted.status_code == 200, accepted.text
        assert replay.status_code == 200
        assert replay.json() == accepted.json()

        before_terminal = _financial_snapshot(client, split)
        reject_candidate, _ = _change(client, split, share=2_500, net=2_500)
        reject_action, reject_fields, _ = _web_form(browser, split, command="reject")
        assert reject_action == (
            f"/web/debts/{split['debt']}/split-changes/{reject_candidate['public_id']}/reject"
        )
        rejected = _post_web(browser, reject_action, reject_fields)
        assert rejected.status_code == 200, rejected.text
        with SessionLocal() as db:
            rejected_row = db.scalar(select(BillSplitChangeProposal).where(
                BillSplitChangeProposal.public_id == reject_candidate["public_id"]))
            assert rejected_row.status == "rejected"
            assert rejected_row.resolved_by_account_id == split["sender_id"]

        withdraw_create_action, withdraw_create_fields, _ = _web_form(browser, split)
        withdraw_create_fields.update(new_share_amount_major="28.00", settlement_net_amount_major="28.00",
                                      reason="Web proposal to withdraw")
        made_for_withdrawal = _post_web(browser, withdraw_create_action, withdraw_create_fields)
        assert made_for_withdrawal.status_code == 200, made_for_withdrawal.text
        with SessionLocal() as db:
            withdraw_candidate = db.scalar(select(BillSplitChangeProposal).where(
                BillSplitChangeProposal.status == "pending"))
            withdraw_candidate_id = withdraw_candidate.public_id
        withdraw_action, withdraw_fields, _ = _web_form(browser, split, command="withdraw")
        assert withdraw_action == (
            f"/web/debts/{split['debt']}/split-changes/{withdraw_candidate_id}/withdraw"
        )
        withdrawn = _post_web(browser, withdraw_action, withdraw_fields)
        assert withdrawn.status_code == 200, withdrawn.text
        with SessionLocal() as db:
            withdrawn_row = db.scalar(select(BillSplitChangeProposal).where(
                BillSplitChangeProposal.public_id == withdraw_candidate_id))
            assert withdrawn_row.status == "withdrawn"
            assert withdrawn_row.resolved_by_account_id == split["sender_id"]
        assert _financial_snapshot(client, split) == before_terminal

        accept_candidate, _ = _change(client, split, share=2_000, net=2_000)
        accept_action, accept_fields, _ = _web_form(browser, split, command="accept")
        assert accept_action == (
            f"/web/debts/{split['debt']}/split-changes/{accept_candidate['public_id']}/accept"
        )
        accepted_web = _post_web(browser, accept_action, accept_fields)
        replayed_web = _post_web(browser, accept_action, accept_fields)
        assert accepted_web.status_code == 200, accepted_web.text
        assert replayed_web.status_code == 200, replayed_web.text
        assert "这次约定操作已完成" in accepted_web.text
        assert "这次约定操作已完成" in replayed_web.text
        with SessionLocal() as db:
            accepted_row = db.scalar(select(BillSplitChangeProposal).where(
                BillSplitChangeProposal.public_id == accept_candidate["public_id"]))
            changes = list(db.scalars(select(BillSplitAgreementChange)))
            assert accepted_row.status == "accepted"
            assert accepted_row.resolved_by_account_id == split["sender_id"]
            assert len(changes) == 2
    finally:
        browser.close()
