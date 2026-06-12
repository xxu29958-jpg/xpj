"""ADR-0029 /web UI smoke tests — inbox + sent rendering."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Account, Expense, Ledger, LedgerMember
from app.routes.web_common import _require_local as _web_require_local
from app.services import bill_split_service as bsplit
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import ensure_utc, now_utc


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


def _seed_receiver(ledger_id: str = "receiver_web", display: str = "B-web") -> tuple[int, str]:
    with SessionLocal() as db:
        acct = Account(display_name=display)
        db.add(acct)
        db.flush()
        ledger = Ledger(ledger_id=ledger_id, name=f"{display} 账本", owner_account_id=acct.id)
        db.add(ledger)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=acct.id, role="owner"))
        db.commit()
        return acct.id, ledger_id


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


# --- inbox + sent rendering -----------------------------------------------


def test_web_inbox_renders_empty_state(web_client: TestClient) -> None:
    response = web_client.get("/web/bill-splits/inbox?ledger_id=owner")
    assert response.status_code == 200, response.text[:300]
    assert "拆账收件箱" in response.text
    assert "还没有拆账邀请" in response.text


def test_web_sent_renders_empty_state(web_client: TestClient) -> None:
    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    assert "已发出的拆账邀请" in response.text
    assert "没有已发起" in response.text


def test_web_sent_lists_invitations(web_client: TestClient) -> None:
    """Send an invitation from owner ledger; sent list renders it.

    Tests rendering of the owner's own sent list (loopback acts as the
    owner). Account-scoped inbox testing under loopback is harder (the
    /web loopback mode picks owner of the *selected ledger* as the
    request account, so an account that isn't owner of any ledger
    visible in owner-console can't be tested here without a cookie
    session). The privacy assertions against inbox-side DTO are covered
    by ``test_bill_split.py::test_inbox_response_omits_sender_internal_ids``."""
    receiver_id, _ = _seed_receiver(ledger_id="receiver_listw")
    expense_id = _make_owner_expense()
    with SessionLocal() as db:
        bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=1500,
        )

    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    assert "Pizza" in response.text
    assert "B-web" in response.text  # receiver_display_name_snapshot


def test_web_sent_omits_receiver_ledger_id(web_client: TestClient) -> None:
    """Sender's sent list must not expose receiver_ledger_id even after
    the receiver has accepted."""
    receiver_id, recv_ledger = _seed_receiver(ledger_id="receiver_send")
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
        bsplit.accept_invitation(
            db,
            public_id=inv.public_id,
            accepting_account_id=receiver_id,
            target_ledger_id=recv_ledger,
        )

    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    body = response.text
    # receiver's target ledger should never appear in HTML.
    assert recv_ledger not in body
    assert "receiver_ledger_id" not in body


# --- form-action failures flash back instead of bare JSON (audit P2 #13) ---


def test_web_split_cancel_after_accept_flashes_conflict_not_json(
    web_client: TestClient,
) -> None:
    """TOCTOU is routine: receiver accepts while the sender's sent page is
    open. The sender's cancel must flash the conflict back onto the sent
    page (303 + readable msg), not escape as a bare-JSON error page."""
    receiver_id, recv_ledger = _seed_receiver(ledger_id="receiver_toctou")
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
        bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_id,
            target_ledger_id=recv_ledger,
        )

    resp = web_client.post(
        f"/web/bill-splits/{public_id}/cancel",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/web/bill-splits/sent")
    followed = web_client.get(location)
    assert followed.status_code == 200
    # The flash is the specific invitation_not_cancellable copy, not the
    # generic server_error fallback (the code now has an ERROR_MESSAGES row).
    assert "无法撤回" in followed.text


def test_web_split_invite_duplicate_pending_flashes_message(
    web_client: TestClient,
) -> None:
    receiver_id, _ = _seed_receiver(ledger_id="receiver_dupinv")
    expense_id = _make_owner_expense()
    first = web_client.post(
        f"/web/expenses/{expense_id}/split-invite",
        data={
            "ledger_id": "owner",
            "receiver_account_id": str(receiver_id),
            "amount_yuan": "12.00",
        },
        follow_redirects=False,
    )
    assert first.status_code == 303

    second = web_client.post(
        f"/web/expenses/{expense_id}/split-invite",
        data={
            "ledger_id": "owner",
            "receiver_account_id": str(receiver_id),
            "amount_yuan": "8.00",
        },
        follow_redirects=False,
    )
    assert second.status_code == 303
    followed = web_client.get(second.headers["location"])
    assert followed.status_code == 200
    assert "待处理拆账邀请" in followed.text


# --- audit P3 #4: ledger NAME in the accept dropdown + local-time display ---


def _seed_expense_in(ledger_id: str, amount_cents: int = 3000) -> int:
    with SessionLocal() as db:
        e = Expense(
            tenant_id=ledger_id,
            amount_cents=amount_cents,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=amount_cents,
            merchant="Sushi",
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(e)
        db.commit()
        return e.id


def test_web_inbox_dropdown_shows_ledger_name_and_local_time(
    web_client: TestClient,
) -> None:
    """ENGINEERING_RULES section 3: UI never surfaces internal ids. The accept
    dropdown must show the ledger NAME (option value keeps the id), and the
    snapshot times must render in the accounting timezone, not as the raw
    ``...+00:00`` UTC repr."""
    sender_id, sender_ledger = _seed_receiver(
        ledger_id="sender_namew", display="B-namew"
    )
    expense_id = _seed_expense_in(sender_ledger)
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=sender_id,
            sender_ledger_id=sender_ledger,
            expense_id=expense_id,
            receiver_account_id=_owner_account_id(),
            amount_cents=1200,
        )
        snapshot_expires = inv.expires_at
        owner_ledger_name = db.query(Ledger).filter(Ledger.ledger_id == "owner").one().name

    response = web_client.get("/web/bill-splits/inbox?ledger_id=owner")
    assert response.status_code == 200
    html = response.text
    # Dropdown: value carries the id, the visible text is the NAME.
    assert f'<option value="owner">{owner_ledger_name}</option>' in html
    assert '<option value="owner">owner</option>' not in html
    # Times: accounting-tz wall clock, not the raw aware-datetime repr.
    expected_expiry = (
        ensure_utc(snapshot_expires).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")
    )
    assert expected_expiry in html
    assert "+00:00" not in html


def test_web_sent_renders_local_time_not_utc_repr(web_client: TestClient) -> None:
    receiver_id, _ = _seed_receiver(ledger_id="receiver_tz", display="B-tz")
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
        snapshot_time = inv.expense_time_snapshot

    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    expected = (
        ensure_utc(snapshot_time).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")
    )
    assert expected in response.text
    assert "+00:00" not in response.text


# --- B16: row-craft (tabular amount + bsplit-table class) -----------------


def test_web_bill_split_tables_use_bsplit_rowcraft_classes(web_client: TestClient) -> None:
    """B16: both pages opt into the精装 row craft (bsplit-table) and keep the
    amount column on the tabular ``.amount`` cell + the local-time ``.num``
    columns (no raw UTC repr)."""
    receiver_id, _ = _seed_receiver(ledger_id="receiver_rc", display="B-rc")
    expense_id = _make_owner_expense()
    with SessionLocal() as db:
        bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=1500,
        )

    sent = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert sent.status_code == 200
    assert 'class="dt-table bsplit-table"' in sent.text
    assert '<td class="amount">' in sent.text
    assert '<td class="num">' in sent.text  # 到期 / 消费时间 列

    inbox = web_client.get("/web/bill-splits/inbox?ledger_id=owner")
    assert inbox.status_code == 200
    assert 'class="dt-table bsplit-table"' in inbox.text


# --- A8: /web edit-page split-invite card ---------------------------------


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
    pointing at the existing cancel route."""
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
