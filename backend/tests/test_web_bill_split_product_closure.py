"""C3b receiver identity and sender deadline product closure."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from test_web_bill_split import _make_owner_expense, _owner_account_id, _seed_receiver

from app.database import SessionLocal
from app.main import app
from app.models import AuthToken, BillSplitInvitation, Device, LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services import bill_split_service as bsplit
from app.services.identity_service import hash_secret, new_session_token
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import ensure_utc, now_utc


def _mint_receiver_web_session(*, account_id: int, ledger_id: str) -> str:
    token_value = new_session_token()
    with SessionLocal() as db:
        device = Device(account_id=account_id, device_name="receiver browser", platform="web")
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(token_value),
                account_id=account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
    return token_value


@pytest.mark.parametrize(
    ("snapshot_name", "visible_ledger_name", "expected"),
    [
        ("我", "我的小票夹", ("来自「我的小票夹」的成员", "")),
        ("我", "", ("未设置姓名的发起人", "")),
        ("小王", "共同账本", ("小王", "来自「共同账本」")),
    ],
)
def test_receiver_sender_presentation_never_reuses_sender_deictic_default(
    snapshot_name: str,
    visible_ledger_name: str,
    expected: tuple[str, str],
) -> None:
    assert bsplit.receiver_sender_presentation(snapshot_name, visible_ledger_name) == expected


@pytest.mark.parametrize(
    ("can_see_sender_ledger", "expected_sender_label"),
    [
        (True, "来自「我的小票夹」的成员"),
        (False, "未设置姓名的发起人"),
    ],
)
def test_web_inbox_replaces_sender_deictic_default_with_authorized_context(
    web_client: TestClient,
    *,
    can_see_sender_ledger: bool,
    expected_sender_label: str,
) -> None:
    receiver_id, receiver_ledger = _seed_receiver(ledger_id="receiver_sender_label")
    if can_see_sender_ledger:
        with SessionLocal() as db:
            db.add(LedgerMember(ledger_id="owner", account_id=receiver_id, role="member"))
            db.commit()
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
    token = _mint_receiver_web_session(account_id=receiver_id, ledger_id=receiver_ledger)
    public_client = TestClient(
        app,
        base_url="https://api.example.com",
        client=("203.0.113.20", 50002),
    )

    response = public_client.get(
        f"/web/bill-splits/inbox?ledger_id={receiver_ledger}",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"},
    )

    assert response.status_code == 200, response.text
    assert expected_sender_label in response.text
    assert '<span class="bsplit-sender">我</span>' not in response.text


def test_web_sent_shows_absolute_deadline_for_terminal_states(web_client: TestClient) -> None:
    receiver_id, receiver_ledger = _seed_receiver(ledger_id="receiver_deadline")
    expense_id = _make_owner_expense()
    with SessionLocal() as db:
        invitation = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=1500,
        )
        bsplit.accept_invitation(
            db,
            public_id=invitation.public_id,
            accepting_account_id=receiver_id,
            target_ledger_id=receiver_ledger,
        )
        deadline = ensure_utc(invitation.expires_at).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")

    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    assert f"原定截止 {deadline}" in response.text
    assert "/cancel" not in response.text


def test_web_sent_expired_row_shows_actual_expiry_boundary(web_client: TestClient) -> None:
    receiver_id, _ = _seed_receiver(ledger_id="receiver_deadline_exp")
    expense_id = _make_owner_expense()
    with SessionLocal() as db:
        invitation = bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=1500,
        )
        public_id = invitation.public_id
    past = now_utc() - timedelta(days=1)
    with SessionLocal() as db:
        db.execute(
            update(BillSplitInvitation)
            .where(BillSplitInvitation.public_id == public_id)
            .values(expires_at=past)
        )
        db.commit()
    boundary = ensure_utc(past).astimezone(accounting_zone()).strftime("%Y-%m-%d %H:%M")

    response = web_client.get("/web/bill-splits/sent?ledger_id=owner")
    assert response.status_code == 200
    assert f"已于 {boundary} 过期" in response.text
    assert "/cancel" not in response.text
