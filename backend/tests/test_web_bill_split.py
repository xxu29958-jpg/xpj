"""ADR-0029 /web UI smoke tests — inbox + sent rendering."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Account, Expense, Ledger, LedgerMember
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
