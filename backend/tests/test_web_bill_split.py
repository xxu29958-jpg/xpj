"""ADR-0029 /web UI smoke tests — inbox + sent rendering."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.database import SessionLocal
from app.main import app
from app.models import Account, BillSplitInvitation, Expense, Ledger, LedgerMember
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
    assert "没有待处理的拆账邀请" in response.text


def test_web_sent_renders_empty_state(web_client: TestClient) -> None:
    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    assert "已发出的拆账邀请" in response.text
    assert "还没有已发出的拆账邀请" in response.text


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


def test_web_split_accept_redirects_to_canonical_fact_receipt(
    web_client: TestClient,
) -> None:
    sender_id, sender_ledger = _seed_receiver(
        ledger_id="sender_receipt",
        display="家人甲",
    )
    expense_id = _seed_expense_in(sender_ledger, amount_cents=3000)
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=sender_id,
            sender_ledger_id=sender_ledger,
            expense_id=expense_id,
            receiver_account_id=_owner_account_id(),
            amount_cents=1200,
        )
        public_id = inv.public_id
        owner_ledger_name = db.query(Ledger).filter(Ledger.ledger_id == "owner").one().name

    response = web_client.post(
        f"/web/bill-splits/{public_id}/accept",
        data={"ledger_id": "owner", "target_ledger_id": "owner"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = urlparse(response.headers["location"])
    query = parse_qs(location.query)
    assert location.path == "/web/bill-splits/inbox"
    assert query["accepted"] == [public_id]
    assert query["flash_type"] == ["success"]

    with SessionLocal() as db:
        accepted = db.query(BillSplitInvitation).filter_by(public_id=public_id).one()
        received_expense_id = accepted.received_expense_id
    assert received_expense_id is not None

    receipt = web_client.get(response.headers["location"])
    assert receipt.status_code == 200
    assert "已接受" in receipt.text
    assert f"已记入 {owner_ledger_name}" in receipt.text
    assert f"/web/expenses/{received_expense_id}/edit?ledger_id=owner&amp;return_to=bill_splits_inbox" in receipt.text

    fact = web_client.get(
        f"/web/expenses/{received_expense_id}/edit",
        params={"ledger_id": "owner", "return_to": "bill_splits_inbox"},
    )
    assert fact.status_code == 200
    assert "返回拆账收件箱" in fact.text


def test_web_split_receipt_does_not_leak_another_receivers_acceptance(
    web_client: TestClient,
) -> None:
    receiver_id, receiver_ledger = _seed_receiver(
        ledger_id="receiver_private_receipt",
        display="家人乙",
    )
    expense_id = _make_owner_expense()
    with SessionLocal() as db:
        inv = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=900,
        )
        public_id = inv.public_id
        _, received = bsplit.accept_invitation(
            db,
            public_id=public_id,
            accepting_account_id=receiver_id,
            target_ledger_id=receiver_ledger,
        )
        received_expense_id = received.id

    page = web_client.get(
        "/web/bill-splits/inbox",
        params={
            "ledger_id": "owner",
            "accepted": public_id,
            "flash_type": "success",
        },
    )
    assert page.status_code == 200
    assert f"/web/expenses/{received_expense_id}/edit" not in page.text


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


def test_web_inbox_target_shows_ledger_name_and_local_time(
    web_client: TestClient,
) -> None:
    """Target choices name the ledger; internal ids stay out of visible copy."""
    sender_id, sender_ledger = _seed_receiver(ledger_id="sender_namew", display="B-namew")
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
    assert 'name="target_ledger_id"' in html
    assert 'value="owner"' in html
    assert owner_ledger_name in html
    assert '<option value="owner">owner</option>' not in html
    # Times: accounting-tz wall clock, not the raw aware-datetime repr.
    expected_expiry = ensure_utc(snapshot_expires).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")
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
    expected = ensure_utc(snapshot_time).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")
    assert expected in response.text
    assert "+00:00" not in response.text


# --- C3b: product surface + truthful TTL/action context -------------------


def test_web_bill_split_pages_use_obligations_product_cards(web_client: TestClient) -> None:
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
    assert 'data-body-stack="product"' in sent.text
    assert sent.text.count("/static/web/product/domains/obligations.css") == 1
    assert "/static/web/pages/bill-splits.css" not in sent.text
    assert 'class="dt-table bsplit-table"' not in sent.text
    assert f"/web/expenses/{expense_id}/edit?ledger_id=owner&amp;return_to=bill_splits_sent" in sent.text
    sent_fact = web_client.get(
        f"/web/expenses/{expense_id}/edit",
        params={"ledger_id": "owner", "return_to": "bill_splits_sent"},
    )
    assert sent_fact.status_code == 200
    assert "返回已发拆账" in sent_fact.text

    # Inbox renders its table only when owner is the RECEIVER — a sent-only
    # seed leaves it on the empty state, so seed an inbound invitation too.
    sender_id, sender_ledger = _seed_receiver(ledger_id="sender_rc", display="B-rc2")
    inbound_expense = _seed_expense_in(sender_ledger)
    with SessionLocal() as db:
        bsplit.create_invitation(
            db,
            sender_account_id=sender_id,
            sender_ledger_id=sender_ledger,
            expense_id=inbound_expense,
            receiver_account_id=_owner_account_id(),
            amount_cents=900,
        )

    inbox = web_client.get("/web/bill-splits/inbox?ledger_id=owner")
    assert inbox.status_code == 200
    assert 'data-body-stack="product"' in inbox.text
    assert inbox.text.count("/static/web/product/domains/obligations.css") == 1
    assert "/static/web/pages/bill-splits.css" not in inbox.text
    assert 'class="dt-table bsplit-table"' not in inbox.text


def test_web_sent_treats_past_ttl_as_expired_and_hides_cancel(
    web_client: TestClient,
) -> None:
    receiver_id, _ = _seed_receiver(ledger_id="receiver_sent_ttl", display="B-sent-ttl")
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
        db.execute(
            update(BillSplitInvitation)
            .where(BillSplitInvitation.public_id == public_id)
            .values(expires_at=now_utc() - timedelta(seconds=1))
        )
        db.commit()

    sent = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert sent.status_code == 200
    assert "已过期" in sent.text
    assert f'action="/web/bill-splits/{public_id}/cancel"' not in sent.text

    cancelled = web_client.post(
        f"/web/bill-splits/{public_id}/cancel",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert cancelled.status_code == 303
    query = parse_qs(urlparse(cancelled.headers["location"]).query)
    assert query["flash_type"] == ["error"]
    followed = web_client.get(cancelled.headers["location"])
    assert 'class="product-feedback product-feedback--error"' in followed.text
