"""Create-proposal settlement regressions on the Web debt detail surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import MemberRepaymentProposal, Repayment
from tests._web_debt_proposal_support import (
    add_pending_proposal,
    proposal_form,
    seed_member_debt,
)


def test_web_invalid_proposal_is_anchored_and_preserves_draft(
    web_client: TestClient,
) -> None:
    public_id, debt_id, _owner_id, _member_id = seed_member_debt(direction="i_owe")
    original = proposal_form(amount_major="not-an-amount", note="这句话不能丢")
    response = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals",
        data=original,
    )

    assert response.status_code == 422
    assert 'id="debt-action-error-proposal_create"' in response.text
    assert 'aria-describedby="debt-action-error-proposal_create"' in response.text
    assert 'value="not-an-amount"' in response.text
    assert 'value="这句话不能丢"' in response.text
    assert f'name="idempotency_key" value="{original["idempotency_key"]}"' in response.text
    with SessionLocal() as db:
        assert db.scalars(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.debt_id == debt_id)
        ).all() == []


def test_web_second_proposal_shows_fresh_pending_owner_and_error(
    web_client: TestClient,
) -> None:
    public_id, debt_id, owner_id, member_id = seed_member_debt(direction="i_owe")
    add_pending_proposal(
        debt_id=debt_id,
        debtor_id=owner_id,
        creditor_id=member_id,
        amount_cents=8_000,
    )
    response = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals",
        data=proposal_form(amount_major="12.00", note="旧页面再次提交"),
    )

    assert response.status_code == 409
    assert 'id="debt-action-error-proposal_create"' in response.text
    assert "这份还款已经发给对方，正在等确认" in response.text
    assert "等家人确认一下" in response.text


def test_member_date_only_proposal_recovers_original_after_lost_reply_and_unreadable_detail(web_client, monkeypatch):
    import app.routes.web_debt_actions as outcomes
    import app.routes.web_debt_proposal_actions as routes
    from tests.test_web_correction_fx_continuation import _NativeForm

    public_id, debt_id, _, _ = seed_member_debt(direction="i_owe", currency="JPY")
    action = f"/web/debts/{public_id}/repayment-proposals"
    identity = ("csrf_token", "idempotency_key", "origin_binding")
    form = _NativeForm(web_client.get(f"/web/debts/{public_id}?ledger_id=owner").text, action, identity_fields=identity)
    form.set("amount_major", "12")
    form.set("paid_at", "2026-09-01")
    form.set("note", "  原留言  ")
    original = {name: form.one(name) for name in form.fields}
    assert "expected_row_version" not in original  # Proposal creation does not change the balance.
    send = routes.create_repayment_proposal_idempotently
    lose_reply = True

    def send_then_lose_reply(*args, **kwargs):
        nonlocal lose_reply
        receipt = send(*args, **kwargs)
        if lose_reply:
            lose_reply = False
            raise AppError("dependency_unavailable", status_code=503)
        return receipt

    def unreadable_detail(*_args, **_kwargs):
        raise AppError("dependency_unavailable", status_code=503)

    monkeypatch.setattr(routes, "create_repayment_proposal_idempotently", send_then_lose_reply)
    monkeypatch.setattr(outcomes, "_render_debt_detail", unreadable_detail)
    unknown = web_client.post(action, data=original)
    assert unknown.status_code == 503
    assert 'data-repayment-result="submitted"' in unknown.text
    retained = _NativeForm(unknown.text, action, identity_fields=identity)
    assert {name: retained.one(name) for name in retained.fields} == original
    accepted = web_client.post(action, data=original)
    assert accepted.status_code == 200 and "这次还款申报已记录" in accepted.text
    assert "还款事实已记录" not in accepted.text
    with SessionLocal() as db:
        proposals = db.scalars(select(MemberRepaymentProposal).where(MemberRepaymentProposal.debt_id == debt_id)).all()
        assert len(proposals) == 1
        proposal = proposals[0]
        assert proposal.proposed_amount_cents == 12 and proposal.paid_at is None
        assert proposal.note == "原留言" and proposal.status == "pending"
        assert proposal.accounting_time_snapshot["precision"] == "date_only"
        assert proposal.accounting_time_snapshot["user_local_date"] == "2026-09-01"
        assert proposal.accounting_time_snapshot["calendar_revision"] == int(original["calendar_revision"])
        assert db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all() == []
