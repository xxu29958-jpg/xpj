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
    assert 'class="dt-table bsplit-table"' in inbox.text
    assert '<td class="amount">' in inbox.text


# --- 遗留 P1-2：解析/渲染按父账单冻结币种（record 权威，不吃 env 漂移） ---


def _make_expense_with_home(amount_cents: int, home_code: str) -> int:
    with SessionLocal() as db:
        e = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            home_currency_code=home_code,
            original_currency_code=home_code,
            original_amount_minor=amount_cents,
            merchant="Soba",
            category="餐饮",
            source="iPhone截图",
            status="confirmed",
            expense_time=now_utc(),
            confirmed_at=now_utc(),
        )
        db.add(e)
        db.commit()
        return e.id


def test_split_invite_parses_by_parent_frozen_currency_not_env(web_client: TestClient, monkeypatch) -> None:
    # P1-2：CNY 父账单 + env=JPY —— "12.00" 按父冻结 CNY 解析成 1200（JPY 口径会拒
    # 小数）；邀请冻结码=CNY。反向：JPY 父账单 + env=CNY —— "1200" 按 JPY 存 1200
    # （CNY 口径会放大成 120000）。
    from app.config import get_settings
    from app.models import BillSplitInvitation

    receiver_id, _ = _seed_receiver(ledger_id="receiver_p12a")
    expense_id = _make_expense_with_home(3000, "CNY")
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        resp = web_client.post(
            f"/web/expenses/{expense_id}/split-invite",
            data={
                "ledger_id": "owner",
                "receiver_account_id": str(receiver_id),
                "amount_yuan": "12.00",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303, resp.text
        with SessionLocal() as db:
            inv = db.query(BillSplitInvitation).order_by(BillSplitInvitation.id.desc()).first()
            assert inv.amount_cents == 1200
            assert inv.home_currency_code == "CNY"
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()

    receiver_id_b, _ = _seed_receiver(ledger_id="receiver_p12b", display="C-web")
    expense_id_b = _make_expense_with_home(1200, "JPY")
    resp_b = web_client.post(
        f"/web/expenses/{expense_id_b}/split-invite",
        data={
            "ledger_id": "owner",
            "receiver_account_id": str(receiver_id_b),
            "amount_yuan": "1200",
        },
        follow_redirects=False,
    )
    assert resp_b.status_code == 303, resp_b.text
    with SessionLocal() as db:
        inv_b = db.query(BillSplitInvitation).order_by(BillSplitInvitation.id.desc()).first()
        assert inv_b.amount_cents == 1200
        assert inv_b.home_currency_code == "JPY"


def test_split_sent_render_uses_invitation_frozen_currency(web_client: TestClient, monkeypatch) -> None:
    # P1-2 渲染腿：JPY 邀请（冻结 JPY 1200）在 env=CNY 下 sent 列表亮 "1200"（不 ÷100、
    # 不补两位小数）。
    from app.config import get_settings

    receiver_id, _ = _seed_receiver(ledger_id="receiver_p12c")
    expense_id = _make_expense_with_home(1200, "JPY")
    with SessionLocal() as db:
        bsplit.create_invitation(
            db,
            sender_account_id=_owner_account_id(),
            sender_ledger_id="owner",
            expense_id=expense_id,
            receiver_account_id=receiver_id,
            amount_cents=1200,
        )
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "CNY")
    get_settings.cache_clear()
    try:
        page = web_client.get("/web/bill-splits/sent?ledger_id=owner")
        assert page.status_code == 200
        assert "1200" in page.text
        assert "12.00" not in page.text
    finally:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
        get_settings.cache_clear()
