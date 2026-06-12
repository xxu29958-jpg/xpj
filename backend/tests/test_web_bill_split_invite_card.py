"""A8 扫尾 W2 — /web edit-page「找家人分摊」发起卡。

Split out of ``test_web_bill_split.py``: the card suite pushed that file past
the 500-line debt gate (files_over_500), same lesson as #46 — new themed
coverage gets its own file instead of banking debt. Helpers are local copies
(test modules don't import each other in this repo; shared seams live in
``api_contract_helpers`` only).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Account, Expense, LedgerMember
from app.routes.web_common import _require_local as _web_require_local
from app.services import bill_split_service as bsplit
from app.services.time_service import now_utc


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    """Bypass LocalOnly so TestClient can hit /web pages."""
    app.dependency_overrides[_web_require_local] = lambda: None
    try:
        yield client
    finally:
        app.dependency_overrides.pop(_web_require_local, None)


def _owner_account_id() -> int:
    with SessionLocal() as db:
        return db.query(Account).order_by(Account.id.asc()).first().id


def _make_owner_expense(amount_cents: int = 4000) -> int:
    with SessionLocal() as db:
        e = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_cents,
            merchant="Pizza",
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(e)
        db.commit()
        return e.id


def _add_owner_ledger_member(display: str = "家人A") -> int:
    """Add a second active member account to the default ``owner`` ledger so the
    发起卡 receiver dropdown has a candidate (the owner itself is filtered as
    ``is_self``). Returns the new account id."""
    with SessionLocal() as db:
        acct = Account(display_name=display)
        db.add(acct)
        db.flush()
        db.add(LedgerMember(ledger_id="owner", account_id=acct.id, role="member"))
        db.commit()
        return acct.id


def test_web_edit_confirmed_shows_split_invite_card(web_client: TestClient) -> None:
    """A confirmed expense with another ledger member renders the发起卡 wired to
    the existing split-invite route, listing the member as a receiver option."""
    _add_owner_ledger_member(display="家人甲")
    expense_id = _make_owner_expense()

    resp = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert resp.status_code == 200, resp.text[:300]
    body = resp.text
    assert "找家人分摊" in body
    assert f'action="/web/expenses/{expense_id}/split-invite"' in body
    assert 'name="receiver_account_id"' in body
    assert "家人甲" in body


def test_web_edit_pending_hides_split_invite_card(web_client: TestClient) -> None:
    """拆账 only makes sense after入账；a pending expense must not show the卡."""
    _add_owner_ledger_member(display="家人乙")
    with SessionLocal() as db:
        e = Expense(
            tenant_id="owner",
            amount_cents=4000,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=4000,
            merchant="Pending Co",
            source="iPhone截图",
            status="pending",
            expense_time=now_utc(),
        )
        db.add(e)
        db.commit()
        pending_id = e.id

    resp = web_client.get(f"/web/expenses/{pending_id}/edit?ledger_id=owner")
    assert resp.status_code == 200
    assert "找家人分摊" not in resp.text


def test_web_edit_received_split_hides_invite_card(web_client: TestClient) -> None:
    """No chain split: a ``bill_split_received`` expense cannot itself be
    re-split, so the发起卡 is hidden (service也会兜底 split_chain_not_allowed)."""
    _add_owner_ledger_member(display="家人丙")
    with SessionLocal() as db:
        e = Expense(
            tenant_id="owner",
            amount_cents=4000,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=4000,
            merchant="Received Split",
            source="bill_split_received",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(e)
        db.commit()
        received_id = e.id

    resp = web_client.get(f"/web/expenses/{received_id}/edit?ledger_id=owner")
    assert resp.status_code == 200
    assert "找家人分摊" not in resp.text


def test_web_edit_invite_card_prompts_when_no_other_members(
    web_client: TestClient,
) -> None:
    """A confirmed expense with no other members still shows the卡 header but
    prompts to invite family first (no receiver dropdown)."""
    expense_id = _make_owner_expense()
    resp = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    assert "找家人分摊" in body
    assert "先邀请家人加入" in body
    assert 'name="receiver_account_id"' not in body


def test_web_split_invite_success_flashes_from_edit_form(
    web_client: TestClient,
) -> None:
    """POSTing the发起卡 form creates the invitation and flashes success on the
    sent page (no-JS 303 path)."""
    receiver_id = _add_owner_ledger_member(display="家人丁")
    expense_id = _make_owner_expense()

    resp = web_client.post(
        f"/web/expenses/{expense_id}/split-invite",
        data={
            "ledger_id": "owner",
            "receiver_account_id": str(receiver_id),
            "amount_yuan": "12.00",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/bill-splits/sent")
    followed = web_client.get(resp.headers["location"])
    assert followed.status_code == 200
    assert "已发起拆账邀请" in followed.text
    assert "家人丁" in followed.text  # receiver snapshot in the sent list


def test_web_split_invite_amount_exceeds_parent_flashes(web_client: TestClient) -> None:
    """Amount over the parent total flashes the server's split error message
    (transparent passthrough), not a bare-JSON page."""
    receiver_id = _add_owner_ledger_member(display="家人戊")
    expense_id = _make_owner_expense(amount_cents=4000)

    resp = web_client.post(
        f"/web/expenses/{expense_id}/split-invite",
        data={
            "ledger_id": "owner",
            "receiver_account_id": str(receiver_id),
            "amount_yuan": "99.00",  # > 40.00 parent
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    followed = web_client.get(resp.headers["location"])
    assert followed.status_code == 200
    assert "拆账金额不能超过原账单金额" in followed.text


def test_web_edit_card_lists_sent_invitation_with_cancel(
    web_client: TestClient,
) -> None:
    """After sending, the发起卡 lists the pending invitation with a 撤回 form
    pointing at the existing cancel route, carrying ``return_expense_id`` so
    the cancel lands back on this edit page (review P3)."""
    receiver_id = _add_owner_ledger_member(display="家人己")
    expense_id = _make_owner_expense()
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=1500,
        )
        public_id = inv.public_id

    resp = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    assert "家人己" in body
    assert f'action="/web/bill-splits/{public_id}/cancel"' in body
    assert "撤回" in body
    assert f'name="return_expense_id" value="{expense_id}"' in body


def test_build_split_invite_context_hidden_for_viewer_render() -> None:
    """Render-side viewer hiding: with ``can_write=False`` the context builder
    returns None so the卡 never renders (POST 403 is enforced separately by
    ``_require_selected_ledger_write`` — see test_web_route_inventory +
    test_web_session_write_gate)."""
    from app.routes.web_bill_split import build_split_invite_context

    expense = {
        "id": 1,
        "status": "confirmed",
        "amount_cents": 4000,
        "is_split_received": False,
    }
    with SessionLocal() as db:
        assert (
            build_split_invite_context(
                db,
                request=None,
                selected_ledger_id="owner",
                expense=expense,
                can_write=False,
            )
            is None
        )
