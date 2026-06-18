"""/web/debts/{id} 成员还款 proposal 状态 + 过往历史 (ADR-0049 债务域 web 面 slice 2b).

只读：在途 pending 渲染成一行关系状态句 (web 描述性非 CTA)，已解决 proposal 沉降进「过往」
(neutral，rejected/expired 不读作失败，永不红)。复用 ``list_repayment_proposals`` 无新端点。
拆出独立文件 (proposal concern) 让 test_web_debts.py 留在 files_over_500 门下。
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember, MemberRepaymentProposal, Repayment
from app.routes.web_debts import (
    _proposal_pending_line,
    _proposal_section,
    _resolved_proposal_row,
)
from app.services.time_service import now_utc

# Uses the shared ``web_client`` fixture (conftest.py) which bypasses the /web loopback
# gate; the loopback web viewer resolves to the ledger owner account.

_COMMITTED_STATUSES = {"confirmed", "partially_confirmed"}


def _owner_account_id(db) -> int:
    owner_account_id = db.scalar(
        select(LedgerMember.account_id)
        .where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner")
        .limit(1)
    )
    assert owner_account_id is not None
    return owner_account_id


def _seed_member_debt_for_proposals(*, direction: str = "i_owe") -> tuple[str, int, int, int]:
    """Seed an 'owner'-ledger member debt and return (public_id, debt_id, owner_id, member_id)
    so proposals can be attached. The loopback web viewer resolves to the ledger owner."""
    with SessionLocal() as db:
        member = Account(display_name="家人")
        db.add(member)
        db.flush()
        owner_account_id = _owner_account_id(db)
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction=direction,
            counterparty_type="member",
            counterparty_account_id=member.id,
            principal_amount_cents=20000,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id, debt.id, owner_account_id, member.id


def _seed_external_debt() -> tuple[str, int, int, int]:
    """Seed an external/manual debt + a spare account, return (public_id, debt_id, owner_id, other_id)
    so a proposal can be attached to prove the external detail still shows no section."""
    with SessionLocal() as db:
        other = Account(display_name="某人")
        db.add(other)
        db.flush()
        owner_account_id = _owner_account_id(db)
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_account_id,
            created_by_account_id=owner_account_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_label="招商信用卡",
            principal_amount_cents=50000,
            home_currency_code="CNY",
            status="open",
            source_type="manual",
        )
        db.add(debt)
        db.commit()
        return debt.public_id, debt.id, owner_account_id, other.id


def _seed_proposal(
    *,
    debt_id: int,
    debtor_id: int,
    creditor_id: int,
    status: str,
    amount_cents: int = 5000,
    note: str | None = None,
    resolved: bool = True,
    days_ago: int = 0,
) -> str:
    """Insert one MemberRepaymentProposal directly (creating proposals goes through the
    debtor↔creditor /api flow; the read-only /web page just renders them).

    A confirmed / partially_confirmed proposal must carry a committed Repayment
    (the §4 status↔committed CHECK), so this mirrors ``_commit_confirmation``:
    insert pending → insert the linked Repayment → flip to the committed status with
    ``committed_repayment_id`` + ``confirmed_amount_cents`` set."""
    with SessionLocal() as db:
        now = now_utc()
        created = now - timedelta(days=days_ago)
        committed = status in _COMMITTED_STATUSES
        proposal = MemberRepaymentProposal(
            debt_id=debt_id,
            debtor_account_id=debtor_id,
            creditor_account_id=creditor_id,
            proposed_by_account_id=debtor_id,
            proposed_amount_cents=amount_cents,
            home_currency_code="CNY",
            paid_at=created,
            note=note,
            # Insert as pending first; the status↔committed CHECK forbids inserting a
            # committed status without a committed_repayment_id, which doesn't exist yet.
            status="pending" if committed else status,
            created_at=created,
            expires_at=created + timedelta(days=30),
            resolved_at=(None if committed else (now if resolved else None)),
            resolved_by_account_id=(None if committed else (creditor_id if resolved else None)),
            idempotency_key=str(uuid4()),
        )
        db.add(proposal)
        db.flush()
        if committed:
            repayment = Repayment(
                debt_id=debt_id,
                amount_cents=amount_cents,
                paid_at=created,
                actor_account_id=creditor_id,
                proposal_id=proposal.id,
                idempotency_key=str(uuid4()),
            )
            db.add(repayment)
            db.flush()
            proposal.status = status
            proposal.committed_repayment_id = repayment.id
            proposal.confirmed_amount_cents = amount_cents
            proposal.resolved_at = now
            proposal.resolved_by_account_id = creditor_id
        db.commit()
        return proposal.public_id


def test_web_debt_detail_pending_proposal_debtor_view(web_client: TestClient) -> None:
    # i_owe member debt → owner (the web viewer) is the debtor. A pending proposal renders as a
    # descriptive relational status line (web read-only, not a confirm CTA), never red.
    public_id, debt_id, owner_id, member_id = _seed_member_debt_for_proposals(direction="i_owe")
    _seed_proposal(debt_id=debt_id, debtor_id=owner_id, creditor_id=member_id,
                   status="pending", resolved=False)
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert "你说你还了这一份，等家人确认一下" in resp.text  # debtor-side pending line
    assert "dt-pill danger" not in resp.text  # member surface never red


def test_web_debt_detail_pending_proposal_creditor_view(web_client: TestClient) -> None:
    # owed_to_me member debt → owner (the web viewer) is the creditor → the descriptive line names
    # the amount the other side says they paid. (web read-only: confirm/reject happen in the App.)
    public_id, debt_id, owner_id, member_id = _seed_member_debt_for_proposals(direction="owed_to_me")
    _seed_proposal(debt_id=debt_id, debtor_id=member_id, creditor_id=owner_id,
                   status="pending", amount_cents=8000, resolved=False)
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert "TA 把 ¥80.00 那份给你啦，看看对不对" in resp.text  # creditor-side pending line w/ amount


def test_web_debt_detail_resolved_history_is_sunk_and_neutral(web_client: TestClient) -> None:
    # Resolved proposals sink into 过往 with day-granularity dates + NEUTRAL pills; a rejected one
    # reads 在对账 (not 已拒绝/失败) and never danger (red-line ②). No list-level totals/counts.
    public_id, debt_id, owner_id, member_id = _seed_member_debt_for_proposals(direction="i_owe")
    _seed_proposal(debt_id=debt_id, debtor_id=owner_id, creditor_id=member_id,
                   status="confirmed", amount_cents=5000, note="微信转的", days_ago=2)
    _seed_proposal(debt_id=debt_id, debtor_id=owner_id, creditor_id=member_id,
                   status="rejected", amount_cents=3000, days_ago=1)
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert "过往" in resp.text  # history block title
    assert "已两清" in resp.text  # confirmed → 已两清 label
    assert "对上" in resp.text  # confirmed date prefix
    # An optional note renders in the history row (the {% if row.note %} path).
    assert "微信转的" in resp.text
    assert "debt-history-note" in resp.text
    assert "在对账" in resp.text  # rejected reads 在对账, NOT failure
    assert "已拒绝" not in resp.text
    assert "失败" not in resp.text
    assert "dt-pill danger" not in resp.text  # all resolved pills neutral
    # §3.4: a confirmed proposal in 过往 is NEUTRAL, never挑成 success green. The debt itself is
    # open (status badge 进行中, neutral), so no success pill should appear anywhere on the page.
    assert "dt-pill ok" not in resp.text


def test_web_debt_detail_resolved_history_collapses_over_three(web_client: TestClient) -> None:
    public_id, debt_id, owner_id, member_id = _seed_member_debt_for_proposals(direction="i_owe")
    for i in range(5):
        _seed_proposal(debt_id=debt_id, debtor_id=owner_id, creditor_id=member_id,
                       status="withdrawn", amount_cents=1000 + i, days_ago=i)
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    # First 3 shown inline, the rest behind a no-JS <details> "查看全部 5 条过往".
    assert "查看全部 5 条过往" in resp.text
    assert "<details class=\"debt-history-more\">" in resp.text


def test_web_debt_detail_member_no_proposals_renders_no_section(web_client: TestClient) -> None:
    # A member debt with zero proposals → the whole proposal section is omitted (no 过往 / status line).
    public_id, _debt_id, _owner_id, _member_id = _seed_member_debt_for_proposals(direction="i_owe")
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert "过往" not in resp.text
    assert "debt-proposal-status" not in resp.text


def test_web_debt_detail_external_has_no_proposal_section(web_client: TestClient) -> None:
    # External debt → businesslike card, no proposal flow — even with a proposal row attached to it
    # (the is_member route gate skips the query AND the template renders the proposal block only in
    # the {% if debt.is_member %} branch). Pins that external never surfaces the proposal section.
    public_id, debt_id, owner_id, other_id = _seed_external_debt()
    _seed_proposal(debt_id=debt_id, debtor_id=owner_id, creditor_id=other_id,
                   status="rejected", amount_cents=3000)
    resp = web_client.get(f"/web/debts/{public_id}")
    assert resp.status_code == 200
    assert "过往" not in resp.text
    assert "debt-proposal-status" not in resp.text
    assert "在对账" not in resp.text  # the attached proposal's status never leaks onto an external card


def _stub_proposal(**overrides) -> SimpleNamespace:
    base = {
        "status": "confirmed",
        "proposed_amount_cents": 5000,
        "home_currency_code": "CNY",
        "note": None,
        "created_at": None,
        "resolved_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_proposal_pending_line_by_role() -> None:
    debtor_pending = _stub_proposal(status="pending")
    assert _proposal_pending_line(debtor_pending, True) == "你说你还了这一份，等家人确认一下"
    creditor_pending = _stub_proposal(status="pending", proposed_amount_cents=8000)
    assert _proposal_pending_line(creditor_pending, False) == "TA 把 ¥80.00 那份给你啦，看看对不对"
    assert _proposal_pending_line(debtor_pending, None) == "他们之间有一笔正在确认"


def test_resolved_proposal_row_date_prefix_and_neutral_status() -> None:
    confirmed = _resolved_proposal_row(_stub_proposal(status="confirmed"))
    assert confirmed["status_label"] == "已两清"
    assert confirmed["date_text"].endswith(" 对上")
    partial = _resolved_proposal_row(_stub_proposal(status="partially_confirmed"))
    assert partial["status_label"] == "收了一部分"
    assert partial["date_text"].endswith(" 收了一部分")
    rejected = _resolved_proposal_row(_stub_proposal(status="rejected"))
    assert rejected["status_label"] == "在对账"  # never 已拒绝/失败
    assert "对上" not in rejected["date_text"]  # no positive prefix for a non-settled close


def test_proposal_section_splits_pending_and_collapses_resolved() -> None:
    # None when entirely empty.
    assert _proposal_section([], True) is None
    # One pending + 4 resolved → pending line + first-3 visible / rest hidden, total label.
    pending = _stub_proposal(status="pending")
    resolved = [_stub_proposal(status="confirmed") for _ in range(4)]
    section = _proposal_section([pending, *resolved], True)
    assert section is not None
    assert section["pending_line"] == "你说你还了这一份，等家人确认一下"
    assert len(section["resolved_visible"]) == 3
    assert len(section["resolved_hidden"]) == 1
    assert section["history_expand_label"] == "查看全部 4 条过往"
    # Resolved-only (no pending) still renders history; pending_line is None.
    resolved_only = _proposal_section(resolved, None)
    assert resolved_only["pending_line"] is None
    assert resolved_only["has_resolved"] is True
