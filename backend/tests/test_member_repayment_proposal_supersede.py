"""ADR-0049 member repayment proposal supersede guards."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.debt_proposal_helpers import (
    _create_member_debt,
    _member_headers,
    _mint_member_actor,
    _propose,
)


def test_replacement_create_requires_seen_pending_proposal(
    client: TestClient, *, identity
) -> None:
    # A second create without naming the pending proposal it saw must not
    # supersede anything; the client has to refresh and send an explicit target.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()

    blocked = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=25000
    )
    assert blocked.status_code == 409, blocked.json()
    assert blocked.json()["error"] == "repayment_proposal_already_pending"

    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert len(proposals) == 1
    assert proposals[0]["public_id"] == first["public_id"]
    assert proposals[0]["status"] == "pending"


def test_stale_replacement_cannot_supersede_newer_pending(
    client: TestClient, *, identity
) -> None:
    # Device A saw P1, device B replaced it with P2, then A's delayed edit must
    # fail instead of superseding P2 without ever seeing it.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    second = _propose(
        client,
        _member_headers(member_token),
        debt["public_id"],
        proposed_amount_cents=25000,
        supersedes_proposal_public_id=first["public_id"],
    ).json()

    stale = _propose(
        client,
        _member_headers(member_token),
        debt["public_id"],
        proposed_amount_cents=30000,
        supersedes_proposal_public_id=first["public_id"],
    )
    assert stale.status_code == 409, stale.json()
    assert stale.json()["error"] == "repayment_proposal_already_pending"

    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    by_id = {p["public_id"]: p for p in proposals}
    assert by_id[first["public_id"]]["status"] == "superseded"
    assert by_id[second["public_id"]]["status"] == "pending"
    assert sum(1 for p in proposals if p["status"] == "pending") == 1
    assert all(p["proposed_amount_cents"] != 30000 for p in proposals)
