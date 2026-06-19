"""/web/receivables 欠我的 (应收) 页 (ADR-0049 债务域 web 面 ⑤c-3 / P3b creditor 发现).

只读 **account-scoped 跨账本** 列出 viewer 作为跨账本 member 债权人的应收 —— bill_split
成员债住在债务人账本,发起人(债权人)在自己账本欠款页看不到,这页补上。每行 communal
关系行(债务人名 + 「我帮你垫的…」关系主句 + 进度条 + 状态徽章,永不红),**纯只读非链接**
(镜像还款捕获审计页);还款由债务人在手机 App 发起、债权人确认。

uses ``web_client`` (conftest) 绕过 /web loopback 门;plain ``client`` 留门给 remote-403。
自包含 seed(``create_bill_split_debt`` 直接造成员债,owner=债务人、counterparty=发起人=
本测 owner=债权人),拆独立文件守 files_over_500。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, Ledger, LedgerMember, Repayment
from app.routes.web_receivables import _receivable_row_view
from app.services.debt_service import create_bill_split_debt
from app.services.time_service import now_utc


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


def _seed_debtor_ledger(display_name: str, ledger_id: str) -> int:
    """A debtor account that owns its own personal ledger (the creditor is NOT a member)."""
    with SessionLocal() as db:
        account = Account(display_name=display_name)
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=ledger_id, name=f"{display_name} 的账本", owner_account_id=account.id))
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="owner"))
        db.commit()
        return account.id


def _seed_receivable(*, creditor_id: int, debtor_id: int, debtor_ledger: str, amount_cents: int = 2500) -> str:
    """Seed the receiver-side member Debt (debtor owes creditor) via the §4 entry."""
    with SessionLocal() as db:
        debt = create_bill_split_debt(
            db,
            ledger_id=debtor_ledger,
            receiver_account_id=debtor_id,
            sender_account_id=creditor_id,
            amount_cents=amount_cents,
            home_currency_code="CNY",
            source_invitation_public_id=str(uuid4()),
            event_time=None,
        )
        db.commit()
        return debt.public_id


def _clear(public_id: str, debtor_id: int) -> None:
    """Drive a receivable cleared: full repayment fact + the stored-status latch."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        db.add(
            Repayment(
                debt_id=debt.id,
                amount_cents=debt.principal_amount_cents,
                paid_at=now_utc(),
                actor_account_id=debtor_id,
                idempotency_key=str(uuid4()),
            )
        )
        debt.status = "cleared"
        db.commit()


def _set_voided(public_id: str) -> None:
    """Latch a receivable voided (status rank 2) — the ordering test only reads status."""
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        debt.status = "voided"
        db.commit()


def _page(web_client: TestClient) -> str:
    resp = web_client.get("/web/receivables?ledger_id=owner")
    assert resp.status_code == 200, resp.text
    return resp.text


# ── gate + empty ─────────────────────────────────────────────────────────────
def test_web_receivables_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/receivables").status_code == 403


def test_web_receivables_empty_renders_premium_empty_state(web_client: TestClient) -> None:
    html = _page(web_client)
    assert "还没有待对上的款" in html
    assert "dt-card--empty" in html


# ── communal open row ────────────────────────────────────────────────────────
def test_web_receivables_open_row_is_communal_with_debtor_name(web_client: TestClient, *, identity) -> None:
    owner_id = _owner_account_id()
    debtor_id = _seed_debtor_ledger("阿明", "receiver_b")
    _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_b")

    html = _page(web_client)
    assert "阿明" in html  # the DEBTOR's name — who owes the creditor
    assert "我帮你垫的" in html  # communal creditor-side headline (viewer_is_debtor False)
    assert "进行中" in html  # member status pill (open)
    assert "debt-progress" in html  # progress bar on open rows
    # Communal, NOT market: no 应付/应收 accounting framing, no amount hero.
    assert "应收" not in html
    assert "应付" not in html
    assert "dh-amt" not in html


def test_web_receivables_cleared_row_receded(web_client: TestClient, *, identity) -> None:
    owner_id = _owner_account_id()
    debtor_id = _seed_debtor_ledger("小红", "receiver_c")
    public_id = _seed_receivable(creditor_id=owner_id, debtor_id=debtor_id, debtor_ledger="receiver_c")
    _clear(public_id, debtor_id)

    html = _page(web_client)
    assert "小红" in html
    assert "已两清" in html  # cleared member status pill
    assert "debt-card-sunk" in html  # cleared rows recede (永不红)
    assert "两清啦" in html  # cleared communal headline


# ── account-scoped cross-ledger aggregation ──────────────────────────────────
def test_web_receivables_aggregates_across_debtor_ledgers(web_client: TestClient, *, identity) -> None:
    owner_id = _owner_account_id()
    d1 = _seed_debtor_ledger("阿明", "receiver_b")
    d2 = _seed_debtor_ledger("小刚", "receiver_d")
    _seed_receivable(creditor_id=owner_id, debtor_id=d1, debtor_ledger="receiver_b")
    _seed_receivable(creditor_id=owner_id, debtor_id=d2, debtor_ledger="receiver_d")

    html = _page(web_client)
    assert "阿明" in html  # receivable from one debtor's ledger
    assert "小刚" in html  # receivable from another debtor's ledger — cross-ledger aggregated


# ── active-first ordering (open before cleared before voided) ─────────────────
def test_web_receivables_active_first_open_before_cleared_before_voided(
    web_client: TestClient, *, identity
) -> None:
    """Open receivables sort before cleared, cleared before voided (active-first),
    even though the service returns status.asc (alphabetical → cleared before open).
    Mirrors the debt list + Android sortReceivablesActiveFirst; without the route
    re-sort the cleared row would render before the open row."""
    owner_id = _owner_account_id()
    d_open = _seed_debtor_ledger("阿明", "recv_open")
    d_cleared = _seed_debtor_ledger("小红", "recv_cleared")
    d_voided = _seed_debtor_ledger("老王", "recv_voided")
    _seed_receivable(creditor_id=owner_id, debtor_id=d_open, debtor_ledger="recv_open")
    pid_cleared = _seed_receivable(creditor_id=owner_id, debtor_id=d_cleared, debtor_ledger="recv_cleared")
    pid_voided = _seed_receivable(creditor_id=owner_id, debtor_id=d_voided, debtor_ledger="recv_voided")
    _clear(pid_cleared, d_cleared)
    _set_voided(pid_voided)

    html = _page(web_client)
    assert html.index("阿明") < html.index("小红") < html.index("老王")


# ── _receivable_row_view pure unit (status tone + recede + communal headline) ─
def _row(**overrides) -> SimpleNamespace:
    base = {
        "counterparty_label": "阿明",
        "counterparty_type": "member",
        "viewer_is_debtor": False,  # the viewer is the creditor (by construction of the list)
        "status": "open",
        "is_forgiven": False,
        "paid_amount_cents": 0,
        "principal_amount_cents": 2500,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_view_open_communal_creditor_headline() -> None:
    view = _receivable_row_view(_row(status="open", paid_amount_cents=0))
    assert view["name"] == "阿明"
    assert view["status_label"] == "进行中"
    assert view["status_tone"] == ""  # neutral, never danger
    assert view["recede"] is False
    assert view["show_progress"] is True
    assert "我帮你垫的" in view["member_headline"]  # creditor side (viewer_is_debtor False)


def test_view_cleared_recedes_and_two_clear_headline() -> None:
    view = _receivable_row_view(_row(status="cleared", paid_amount_cents=2500))
    assert view["status_label"] == "已两清"
    assert view["status_tone"] == "ok"
    assert view["recede"] is True
    assert view["show_progress"] is False
    assert "两清" in view["member_headline"]


def test_view_voided_recedes_neutral() -> None:
    view = _receivable_row_view(_row(status="voided"))
    assert view["status_label"] == "已不算"
    assert view["status_tone"] == ""  # voided is neutral, never danger (红线②)
    assert view["recede"] is True
