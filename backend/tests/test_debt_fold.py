"""ADR-0049 §2 derived fold (slice 1): empty fact tables → remaining == principal.

Exercises the fold helpers directly (not just through the route) so the
derivation rule is pinned independently of response shaping: a freshly created
Debt with no append-only facts folds to ``remaining == principal``, ``paid == 0``,
status ``open``; and principal is frozen — there is no slice-1 path that mutates
it in place (§2).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Debt
from app.schemas import DebtCreateRequest
from app.services.debt_service import (
    compute_paid,
    compute_remaining,
    create_debt,
    derive_status,
)


def _create_external_debt(*, principal_amount_cents: int) -> str:
    with SessionLocal() as db:
        debt = create_debt(
            db,
            tenant_id="owner",
            created_by_account_id=1,
            owner_account_id=1,
            payload=DebtCreateRequest(
                direction="i_owe",
                counterparty_type="external",
                counterparty_label="测试外部债",
                principal_amount_cents=principal_amount_cents,
            ),
        )
        return debt.public_id


def _reload(public_id: str) -> tuple[Debt, int, int]:
    with SessionLocal() as db:
        debt = db.query(Debt).filter(Debt.public_id == public_id).one()
        remaining = compute_remaining(db, debt)
        paid = compute_paid(db, debt)
        return debt, remaining, paid


def test_empty_facts_remaining_equals_principal(client: TestClient, *, identity) -> None:
    public_id = _create_external_debt(principal_amount_cents=25000)
    debt, remaining, _paid = _reload(public_id)
    assert remaining == 25000
    assert remaining == debt.principal_amount_cents
    assert derive_status(debt, remaining) == "open"


def test_empty_facts_paid_is_zero(client: TestClient, *, identity) -> None:
    public_id = _create_external_debt(principal_amount_cents=18000)
    _debt, _remaining, paid = _reload(public_id)
    assert paid == 0


def test_principal_frozen_after_create(client: TestClient, *, identity) -> None:
    # No slice-1 update path exists; re-reading the Debt twice yields the same
    # frozen principal, and the fold never rewrites it as a stored balance.
    public_id = _create_external_debt(principal_amount_cents=33000)
    debt_a, remaining_a, _ = _reload(public_id)
    debt_b, remaining_b, _ = _reload(public_id)
    assert debt_a.principal_amount_cents == 33000
    assert debt_b.principal_amount_cents == 33000
    assert remaining_a == remaining_b == 33000
