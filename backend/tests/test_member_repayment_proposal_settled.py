"""ADR-0049 §3.2 / §0: a settled member Debt cannot accept a new pending proposal.

``create_repayment_proposal`` originally blocked only ``voided`` Debts, so a stale
client could file a new pending proposal against an already ``cleared`` (fully
repaid) or forgiven Debt. Such a proposal can never be confirmed — the §3.2 confirm
overpay check (``amount > remaining_before``) rejects it on a zero-remaining Debt —
so it lingers as a permanently un-confirmable "ghost". The create path now reads the
authoritative fold under the §2.1 parent lock and refuses ``remaining <= 0`` with a
``state_conflict`` (409). These tests pin both the refusal AND that a Debt with real
remaining is still proposable (the gate is ``remaining`` left, not "any repaid").

Split into its own file: ``test_member_repayment_proposal.py`` is already near the
500-line debt gate, so this cohesive settled-Debt cohort lives here.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.debt_proposal_helpers import (
    _create_member_debt,
    _idem,
    _member_headers,
    _mint_member_actor,
    _propose,
)


def test_create_proposal_on_repayment_cleared_debt_is_refused(
    client: TestClient, *, identity
) -> None:
    # Debtor proposes the full amount; creditor confirms → Debt cleared (remaining 0).
    # A new proposal on the cleared Debt is refused (state_conflict 409) instead of
    # leaving a ghost pending the confirm check would always reject.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=member_id,
        principal_amount_cents=20000,
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 201, confirm.json()
    assert confirm.json()["remaining_amount_cents"] == 0
    assert confirm.json()["status"] == "cleared"

    refused = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=5000
    )
    assert refused.status_code == 409, refused.json()
    assert refused.json()["error"] == "state_conflict"


def test_create_proposal_on_forgiven_debt_is_refused(client: TestClient, *, identity) -> None:
    # Creditor forgives the whole open member Debt → cleared (remaining 0, forgiven).
    # The debtor cannot then propose a repayment on a Debt that no longer owes
    # anything (forgiveness, like a full repayment, drives the fold to 0).
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=member_id,
        principal_amount_cents=30000,
    )
    forgive = client.post(
        f"/api/debts/{debt['public_id']}/forgive",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert forgive.status_code == 201, forgive.json()
    assert forgive.json()["remaining_amount_cents"] == 0
    assert forgive.json()["is_forgiven"] is True

    refused = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=10000
    )
    assert refused.status_code == 409, refused.json()
    assert refused.json()["error"] == "state_conflict"


def test_create_proposal_on_partially_repaid_debt_still_allowed(
    client: TestClient, *, identity
) -> None:
    # The gate is "remaining left", NOT "anything repaid": a partially repaid Debt
    # (remaining > 0) still accepts a new proposal. Pins that the refusal keys off
    # compute_remaining<=0 and is not over-broadened to "any prior repayment".
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=member_id,
        principal_amount_cents=50000,
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{first['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"confirmed_amount_cents": 20000, "expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 201, confirm.json()
    assert confirm.json()["remaining_amount_cents"] == 30000  # still owes 30000

    again = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=10000
    )
    assert again.status_code == 201, again.json()
    assert again.json()["status"] == "pending"


def test_settled_gate_sits_below_idempotency_claim_replay_hits_original(
    client: TestClient, *, identity
) -> None:
    # The settled gate lives INSIDE create_repayment_proposal, BELOW the [[0042]]
    # idempotency claim the route takes first. So replaying a create (SAME key) whose
    # debt has since cleared HIT-replays the original proposal — it never re-enters the
    # service, so the new remaining<=0 gate is not re-evaluated — while a FRESH key on
    # the now-cleared debt is refused. Pins that a refactor moving the gate above the
    # claim (or re-validating on HIT) cannot silently break replay idempotency for an
    # already-filed proposal.
    member_id, member_token = _mint_member_actor()
    member_headers = _member_headers(member_token)
    debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=member_id,
        principal_amount_cents=20000,
    )
    key = str(uuid4())
    created = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers={**member_headers, "Idempotency-Key": key},
        json={"proposed_amount_cents": 20000},
    )
    assert created.status_code == 201, created.json()
    proposal_id = created.json()["public_id"]

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal_id}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 201, confirm.json()
    assert confirm.json()["remaining_amount_cents"] == 0  # debt cleared

    # SAME-key replay HITs the original (now confirmed) proposal, NOT the new 409 gate.
    replay = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers={**member_headers, "Idempotency-Key": key},
        json={"proposed_amount_cents": 20000},
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == proposal_id
    assert replay.json()["status"] == "confirmed"

    # A FRESH-key create on the cleared debt is refused by the settled gate.
    fresh = _propose(
        client, member_headers, debt["public_id"], proposed_amount_cents=5000
    )
    assert fresh.status_code == 409, fresh.json()
    assert fresh.json()["error"] == "state_conflict"
