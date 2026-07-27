"""DB seed helpers shared by the web member-repayment-proposal confirm tests.

Kept out of the test modules so both ``test_web_debt_proposal_confirm_amount.py``
(D3 field contract + N-1 legacy compat) and ``test_web_debt_proposal_confirm_anchor.py``
(P2 submission-scoped 422 anchoring) seed the same creditor-view scenario without
copying builders (and each test module stays under the 500-LOC codebase gate).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

import app.routes.web_debt_proposal_actions as proposal_routes
from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember, MemberRepaymentProposal
from app.routes.web_common import LedgerOption
from app.services.time_service import now_utc


def owner_account_id(db) -> int:
    account_id = db.scalar(
        select(LedgerMember.account_id).where(LedgerMember.ledger_id == "owner", LedgerMember.role == "owner").limit(1)
    )
    assert account_id is not None
    return account_id


def seed_creditor_view(*, currency: str = "CNY") -> tuple[str, int, int, int, str]:
    """Seed an 'owed_to_me' member debt + one pending proposal from the family member;
    the loopback web viewer (owner) is the creditor who can confirm. Returns
    (debt_public_id, debt_id, owner_id, member_id, proposal_public_id)."""
    with SessionLocal() as db:
        member = Account(display_name="家人")
        db.add(member)
        db.flush()
        owner_id = owner_account_id(db)
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner_id,
            created_by_account_id=owner_id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=member.id,
            principal_amount_cents=20000,
            home_currency_code=currency,
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.flush()
        proposal_public_id = add_pending_proposal_in(
            db,
            debt_id=debt.id,
            debtor_id=member.id,
            creditor_id=owner_id,
            amount_cents=8_000,
            currency=currency,
        )
        db.commit()
        return debt.public_id, debt.id, owner_id, member.id, proposal_public_id


def add_pending_proposal_in(
    db,
    *,
    debt_id: int,
    debtor_id: int,
    creditor_id: int,
    amount_cents: int,
    currency: str = "CNY",
) -> str:
    """Insert one pending proposal row on ``db`` (caller commits)."""
    created = now_utc()
    proposal = MemberRepaymentProposal(
        debt_id=debt_id,
        debtor_account_id=debtor_id,
        creditor_account_id=creditor_id,
        proposed_by_account_id=debtor_id,
        proposed_amount_cents=amount_cents,
        home_currency_code=currency,
        paid_at=created,
        status="pending",
        created_at=created,
        expires_at=created + timedelta(days=30),
        idempotency_key=str(uuid4()),
    )
    db.add(proposal)
    db.flush()
    return proposal.public_id


def add_pending_proposal(
    *,
    debt_id: int,
    debtor_id: int,
    creditor_id: int,
    amount_cents: int,
    currency: str = "CNY",
) -> str:
    """Attach one more pending proposal to an existing debt (legal once any previous
    pending row is resolved — ``uq_mrp_one_pending_per_debt`` only gates pending)."""
    with SessionLocal() as db:
        public_id = add_pending_proposal_in(
            db,
            debt_id=debt_id,
            debtor_id=debtor_id,
            creditor_id=creditor_id,
            amount_cents=amount_cents,
            currency=currency,
        )
        db.commit()
        return public_id


def resolve_proposal_out_of_band(proposal_public_id: str, *, resolver_account_id: int) -> None:
    """Flip a pending proposal to withdrawn as if the other端 resolved it between the
    creditor's page load and submit (P2 race) — direct row update, same shape as the
    withdraw path leaves behind (withdrawn needs no committed Repayment)."""
    with SessionLocal() as db:
        proposal = db.scalar(
            select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal_public_id)
        )
        assert proposal is not None
        proposal.status = "withdrawn"
        proposal.resolved_at = now_utc()
        proposal.resolved_by_account_id = resolver_account_id
        db.commit()


def row_version_of(debt_id: int) -> int:
    with SessionLocal() as db:
        debt = db.get(Debt, debt_id)
        assert debt is not None
        return debt.row_version


def proposal_form(**values: str) -> dict[str, str]:
    return {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "idempotency_key": str(uuid4()),
        **values,
    }


def post_confirm(web_client, debt_public_id: str, proposal_public_id: str, **values: str):
    return web_client.post(
        f"/web/debts/{debt_public_id}/repayment-proposals/{proposal_public_id}/confirm",
        data=proposal_form(**values),
        follow_redirects=False,
    )


def viewer_role_only(monkeypatch) -> None:
    """Force the selected ledger option to role=viewer (只读角色路径)。"""
    monkeypatch.setattr(
        proposal_routes,
        "_list_ledger_options",
        lambda _db: [
            LedgerOption(
                ledger_id="owner",
                name="家庭账本",
                role="viewer",
                is_default=True,
                pending_count=0,
                confirmed_count=0,
            )
        ],
    )
