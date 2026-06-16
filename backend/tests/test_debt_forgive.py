"""ADR-0049 §3.7 / §4 creditor forgiveness ("算了，不用还了"), slice 8e-3.

The creditor unilaterally waives a member Debt's remaining: a one-sided Communal
gift (benefits the debtor only, no adverse interest), so it needs NO debtor
confirmation — unlike a member void / principal-raising adjustment (§3.3 / §3.5).
It is member-Debt + creditor only, fold-changing, and folds the Debt to ``cleared``
(NOT ``voided``) via a ``DebtForgiveness`` subtraction whose amount is the
``remaining_before`` snapshotted under the §2.1 lock.

These pin: the fold (``principal − repayments − forgiveness == 0``), the
``is_forgiven`` response flag distinguishing forgive from settle, the member +
creditor guards, zero-remaining / OCC / participant scope, idempotent replay,
pending-proposal supersede (§4 F5), the §6/F13 goal-integrity resolution (forgive =
completion, no review), and the auth / idempotency-key contract.

Fold / fact assertions read the rendered API response or a read-only query of the
append-only fact tables, never a mutating DB peek.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Debt, DebtForgiveness, MemberRepaymentProposal, Repayment
from app.services.time_service import now_utc
from tests.debt_proposal_helpers import (
    _create_external_debt,
    _create_member_debt,
    _member_headers,
    _mint_member_actor,
    _propose,
)
from tests.test_bill_split_debt_linkage import _invite
from tests.test_member_repayment_proposal_cross_ledger import (
    _accept_into,
    _debt_public_id_for,
    _mint_app_token,
    _seed_personal_ledger,
)


@pytest.fixture
def debt_rollout_on(monkeypatch: pytest.MonkeyPatch):
    """Enable the §4 bill-split → Debt linkage for the cross-ledger forgive tests."""
    monkeypatch.setenv("DEBT_ROLLOUT_ENABLED", "true")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _forgive(
    client: TestClient,
    headers: dict[str, str],
    debt_public_id: str,
    *,
    expected_row_version: int,
    idempotency_key: str | None = None,
    json_body: dict | None = None,
):
    return client.post(
        f"/api/debts/{debt_public_id}/forgive",
        headers={**headers, "Idempotency-Key": idempotency_key or str(uuid4())},
        json=json_body or {"expected_row_version": expected_row_version},
    )


def _forgivenesses(debt_public_id: str) -> list[DebtForgiveness]:
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        return list(
            db.scalars(select(DebtForgiveness).where(DebtForgiveness.debt_id == debt.id))
        )


def _seed_repayment(debt_public_id: str, *, amount_cents: int, actor_account_id: int) -> None:
    """Insert one committed repayment fact directly (the fold reads it).

    Member-Debt repayments commit via the §3.2 proposal-confirm flow, but this slice
    only needs a prior repayment to exercise ``forgiveness == remaining_before`` (not
    the full principal); seeding it directly keeps the fold assertion focused (the
    ORM seed mirrors ``_create_member_debt``). Does NOT bump the parent row_version.
    """
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        db.add(
            Repayment(
                debt_id=debt.id,
                amount_cents=amount_cents,
                paid_at=now_utc(),
                actor_account_id=actor_account_id,
                idempotency_key=str(uuid4()),
            )
        )
        db.commit()


# ── happy path: creditor forgives, Debt folds to cleared(forgiven) ───────────


def test_creditor_forgives_full_open_debt(client: TestClient, *, identity) -> None:
    # direction='owed_to_me' → debtor=member, creditor=owner (identity). The owner waives
    # the whole remaining: cleared, is_forgiven, paid stays 0 (forgiveness is NOT a payment),
    # exactly one DebtForgiveness fact = principal.
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    resp = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["status"] == "cleared"
    assert body["remaining_amount_cents"] == 0
    assert body["paid_amount_cents"] == 0  # a gift, not a payment
    assert body["is_forgiven"] is True
    assert body["viewer_is_debtor"] is False  # owner is the creditor
    assert body["row_version"] == 2

    facts = _forgivenesses(debt["public_id"])
    assert len(facts) == 1
    assert facts[0].amount_cents == 50000
    with SessionLocal() as db:
        stored = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        assert stored.status == "cleared"  # latched cleared, NOT voided


def test_creditor_forgives_after_partial_repayment_clears(client: TestClient, *, identity) -> None:
    # principal 50000, a 20000 repayment already committed → remaining_before 30000. The
    # forgiveness amount is the remaining (30000), NOT the principal, so the fold is exactly
    # principal − repayment − forgiveness == 0 and paid reflects only the real 20000 payment.
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    _seed_repayment(debt["public_id"], amount_cents=20000, actor_account_id=member_id)

    resp = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["remaining_amount_cents"] == 0
    assert body["paid_amount_cents"] == 20000
    assert body["status"] == "cleared"
    assert body["is_forgiven"] is True

    facts = _forgivenesses(debt["public_id"])
    assert len(facts) == 1
    assert facts[0].amount_cents == 30000  # remaining_before, not the principal


def test_repayment_cleared_debt_is_not_forgiven(client: TestClient, *, identity) -> None:
    # A Debt cleared by a FULL repayment (no forgiveness) reads is_forgiven=False — the flag
    # distinguishes "被请客" from a real settle, so the §5.6 celebration fork can tell them apart.
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    _seed_repayment(debt["public_id"], amount_cents=50000, actor_account_id=member_id)

    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["status"] == "cleared"
    assert detail.json()["is_forgiven"] is False  # cleared by repayment, not forgiven


# ── authorization: member-Debt only, creditor only ───────────────────────────


def test_debtor_cannot_forgive(client: TestClient, *, identity) -> None:
    # The debtor (member) cannot give up the creditor's claim — only the creditor can. 403,
    # no fact recorded, the Debt stays open.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    resp = _forgive(client, _member_headers(member_token), debt["public_id"], expected_row_version=1)
    assert resp.status_code == 403, resp.json()
    assert resp.json()["error"] == "repayment_proposal_creditor_only"
    assert _forgivenesses(debt["public_id"]) == []
    with SessionLocal() as db:
        assert db.scalar(select(Debt).where(Debt.public_id == debt["public_id"])).status == "open"


def test_external_debt_cannot_be_forgiven(client: TestClient, *, identity) -> None:
    # Forgiveness is the Communal escape valve for MEMBER Debt; an external Debt already has
    # the §3.5 direct void. 409 member-only, no fact.
    debt = _create_external_debt(client, identity.app_headers)
    resp = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=debt["row_version"])
    assert resp.status_code == 409, resp.json()
    assert resp.json()["error"] == "repayment_proposal_requires_member_debt"
    assert _forgivenesses(debt["public_id"]) == []


# ── zero-remaining / OCC / scope ─────────────────────────────────────────────


def test_forgive_already_settled_debt_is_rejected(client: TestClient, *, identity) -> None:
    # Forgiving a Debt that already folds to 0 (fully repaid, or already forgiven) is a
    # state_conflict — recording a 0-amount fact would pollute history and could trip the
    # §5 celebration. The second forgive after a first must also 409 (re-forgive).
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    first = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1)
    assert first.status_code == 201, first.json()
    again = _forgive(
        client, identity.app_headers, debt["public_id"], expected_row_version=first.json()["row_version"]
    )
    assert again.status_code == 409, again.json()
    assert again.json()["error"] == "state_conflict"
    assert len(_forgivenesses(debt["public_id"])) == 1  # no second fact


def test_forgive_stale_row_version_conflicts(client: TestClient, *, identity) -> None:
    # A stale expected_row_version (the user acted on stale Debt state) is rejected by the
    # §2.1 fence with state_conflict; no forgiveness fact is recorded.
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    resp = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=999)
    assert resp.status_code == 409, resp.json()
    assert resp.json()["error"] == "state_conflict"
    assert _forgivenesses(debt["public_id"]) == []


def test_non_participant_cannot_forgive(client: TestClient, *, identity, debt_rollout_on) -> None:
    # A third account, neither debtor nor creditor and not a member of the Debt's ledger,
    # gets debt_not_found (cross-ledger existence hiding) — no leak that the Debt exists.
    receiver_id = _seed_personal_ledger(name="B-fhide", ledger_id="receiver_fhide")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_fhide")
    debt_public_id = _debt_public_id_for(public_id)

    stranger_id = _seed_personal_ledger(name="C-f", ledger_id="stranger_cf")
    stranger_token = _mint_app_token(account_id=stranger_id, ledger_id="stranger_cf")

    resp = _forgive(
        client, {"Authorization": f"Bearer {stranger_token}"}, debt_public_id, expected_row_version=1
    )
    assert resp.status_code == 404, resp.json()
    assert resp.json()["error"] == "debt_not_found"
    assert _forgivenesses(debt_public_id) == []


def test_cross_ledger_creditor_forgives(client: TestClient, *, identity, debt_rollout_on) -> None:
    # §5.2: the bill-split creditor (sender) is NOT a member of the receiver's private ledger,
    # yet can forgive the obligation. The response is the Debt shell (ledger id redacted) and
    # folds to cleared(forgiven).
    receiver_id = _seed_personal_ledger(name="B-fwd", ledger_id="receiver_fwd")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_fwd")
    debt_public_id = _debt_public_id_for(public_id)

    detail = client.get(f"/api/debts/{debt_public_id}", headers=identity.app_headers)
    assert detail.json()["viewer_is_debtor"] is False  # the sender is the creditor
    row_version = detail.json()["row_version"]

    resp = _forgive(client, identity.app_headers, debt_public_id, expected_row_version=row_version)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["ledger_id"] is None  # cross-ledger shell
    assert body["status"] == "cleared"
    assert body["remaining_amount_cents"] == 0
    assert body["is_forgiven"] is True
    assert len(_forgivenesses(debt_public_id)) == 1


# ── idempotency / pending-proposal supersede ─────────────────────────────────


def test_forgive_is_idempotent_on_replay(client: TestClient, *, identity) -> None:
    # A lost-response replay of the same key returns the canonical cleared Debt and records
    # exactly one forgiveness fact (no second fold change).
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    key = str(uuid4())
    first = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1, idempotency_key=key)
    assert first.status_code == 201, first.json()
    assert first.json()["is_forgiven"] is True

    replay = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1, idempotency_key=key)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["status"] == "cleared"
    assert replay.json()["is_forgiven"] is True
    assert len(_forgivenesses(debt["public_id"])) == 1  # exactly one despite the replay


def test_forgive_idempotency_fingerprint_is_actor_scoped(client: TestClient, *, identity) -> None:
    # §3.6 includes actor_account_id in the forgive fingerprint. A forgive HIT path returns before
    # the creditor guard re-runs, so a DIFFERENT same-ledger actor (here the debtor) reusing the
    # creditor's successful key must be a fingerprint MISMATCH (422 idempotency_key_reused), never a
    # HIT that would serve them the cleared Debt past the creditor guard.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    key = str(uuid4())
    first = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1, idempotency_key=key)
    assert first.status_code == 201, first.json()

    # The debtor replays the creditor's key → actor-scoped fingerprint mismatch, not a HIT.
    replay = _forgive(
        client, _member_headers(member_token), debt["public_id"], expected_row_version=1, idempotency_key=key
    )
    assert replay.status_code == 422, replay.json()
    assert replay.json()["error"] == "idempotency_key_reused"
    assert len(_forgivenesses(debt["public_id"])) == 1  # the replay committed no second fact


def test_forgive_supersedes_pending_proposal(client: TestClient, *, identity) -> None:
    # §4 F5: a debtor's in-flight "I paid" proposal is moot once forgiven. Forgive sweeps the
    # pending proposal to 'superseded' in the same transaction, so the creditor cannot later
    # "confirm" a repayment on an already-cleared Debt.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000)
    assert proposal.status_code == 201, proposal.json()
    proposal_public_id = proposal.json()["public_id"]

    resp = _forgive(client, identity.app_headers, debt["public_id"], expected_row_version=1)
    assert resp.status_code == 201, resp.json()
    assert resp.json()["status"] == "cleared"
    assert resp.json()["is_forgiven"] is True

    with SessionLocal() as db:
        stored = db.scalar(
            select(MemberRepaymentProposal).where(
                MemberRepaymentProposal.public_id == proposal_public_id
            )
        )
        assert stored.status == "superseded"
        assert stored.resolved_at is not None


# ── auth / idempotency-key contract ──────────────────────────────────────────


def test_forgive_requires_idempotency_key(client: TestClient, *, identity) -> None:
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    resp = client.post(
        f"/api/debts/{debt['public_id']}/forgive",
        headers=identity.app_headers,
        json={"expected_row_version": 1},
    )
    assert resp.status_code == 422, resp.json()
    assert resp.json()["error"] == "idempotency_key_required"


def test_forgive_requires_auth(client: TestClient, *, identity) -> None:
    # strict-401: a write with no auth is rejected before any business (the route-matrix gate
    # requires this for every mutating route).
    member_id, _ = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    resp = client.post(
        f"/api/debts/{debt['public_id']}/forgive",
        headers={"Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 1},
    )
    assert resp.status_code == 401, resp.json()


# ── §6 / F13 goal integrity: forgive = completion, NOT a review trigger ──────


def test_forgiving_goal_linked_debt_stays_achieved_without_review(client: TestClient, *, identity) -> None:
    # ADR §3.7 open-item resolution: a forgiven Debt folds to ``cleared`` (a genuine
    # completion), so a debt_repayment goal that links it counts it toward achievement and does
    # NOT raise the §6/F13 integrity review — UNLIKE a DebtVoid (→ voided → needs_review). The
    # owner is the DEBTOR here (direction='i_owe'); the member creditor forgives.
    from tests.debt_repayment_goal_helpers import _create_debt_goal

    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="i_owe", member_account_id=member_id
    )
    goal_resp = _create_debt_goal(
        client, identity.app_headers, name="还清家人", debt_public_ids=[debt["public_id"]]
    )
    assert goal_resp.status_code == 201, goal_resp.json()
    goal_public_id = goal_resp.json()["public_id"]
    assert goal_resp.json()["debt_repayment"]["evaluation_state"] == "in_progress"

    # The member (creditor, since owner i_owe → creditor=member) forgives the owner's debt.
    forgive = _forgive(client, _member_headers(member_token), debt["public_id"], expected_row_version=1)
    assert forgive.status_code == 201, forgive.json()
    assert forgive.json()["is_forgiven"] is True

    goal = client.get(f"/api/goals/{goal_public_id}", headers=identity.app_headers)
    assert goal.status_code == 200, goal.json()
    evaluation = goal.json()["debt_repayment"]
    assert evaluation["evaluation_state"] == "achieved"  # forgiven debt counts as cleared
    assert evaluation["needs_review"] is False  # forgive ≠ void → no integrity review
