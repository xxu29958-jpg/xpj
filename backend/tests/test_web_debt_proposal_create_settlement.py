"""Create-proposal settlement regressions on the Web debt detail surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import MemberRepaymentProposal
from tests._web_debt_proposal_support import (
    add_pending_proposal,
    proposal_form,
    seed_member_debt,
)


def test_web_invalid_proposal_is_anchored_and_preserves_draft(
    web_client: TestClient,
) -> None:
    public_id, debt_id, _owner_id, _member_id = seed_member_debt(direction="i_owe")
    response = web_client.post(
        f"/web/debts/{public_id}/repayment-proposals",
        data=proposal_form(
            amount_major="not-an-amount",
            note="这句话不能丢",
        ),
    )

    assert response.status_code == 422
    assert 'id="debt-action-error-proposal_create"' in response.text
    assert 'aria-describedby="debt-action-error-proposal_create"' in response.text
    assert 'value="not-an-amount"' in response.text
    assert 'value="这句话不能丢"' in response.text
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
