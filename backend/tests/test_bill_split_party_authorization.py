"""Party-authorization guards on bill-split transitions (BUG-1).

The ``invitation_not_yours`` 403 guard in ``bill_split_service/_transitions.py``
(accept / reject / cancel) was live but had **zero** tests asserting a wrong
account is rejected — only the happy-path route tests and the concurrency races
covered these endpoints (2026-06-14 known-bugs BUG-1, a GA-blocker). It matters
because ``get_invitation`` (``_query.py``) is not tenant-scoped — it looks the
invitation up by ``public_id`` alone — so this party check is the *sole*
compensating control against a non-party touching another tenant's invitation.
Pin it on every transition, plus the guard's precedence over state resolution
(it must fire before any settled/expiry branch so a non-party cannot probe
invitation state).

The bearer-token helper is shared with
``test_bill_split_security_regressions`` rather than duplicated.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_bill_split import _make_expense_for_owner, _seed_receiver
from tests.test_bill_split_security_regressions import _bearer_for_account_ledger


def _create_invited_split(
    client: TestClient,
    identity,
    *,
    receiver_account_id: int,
    amount_cents: int = 2500,
) -> str:
    """Owner sends a split invite to ``receiver_account_id``; return its public_id."""
    expense_id = _make_expense_for_owner()
    resp = client.post(
        f"/api/expenses/{expense_id}/split-invite",
        headers=identity.app_headers,
        json={"receiver_account_id": receiver_account_id, "amount_cents": amount_cents},
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["public_id"]


def test_accept_route_rejects_non_party_account(
    client: TestClient, *, identity
) -> None:
    """A third account that is neither sender nor receiver cannot accept."""
    receiver_account_id = _seed_receiver(
        name="B-nonparty-accept", ledger_id="receiver_nonparty_accept"
    )
    outsider_account_id = _seed_receiver(
        name="C-outsider-accept", ledger_id="outsider_accept"
    )
    public_id = _create_invited_split(
        client, identity, receiver_account_id=receiver_account_id
    )

    resp = client.post(
        f"/api/bill-splits/{public_id}/accept",
        headers=_bearer_for_account_ledger(outsider_account_id, "outsider_accept"),
        json={"target_ledger_id": "outsider_accept"},
    )

    assert resp.status_code == 403, resp.json()
    assert resp.json()["error"] == "invitation_not_yours"


def test_reject_route_rejects_non_party_account(
    client: TestClient, *, identity
) -> None:
    """Only the receiver may reject; a non-party gets 403."""
    receiver_account_id = _seed_receiver(
        name="B-nonparty-reject", ledger_id="receiver_nonparty_reject"
    )
    outsider_account_id = _seed_receiver(
        name="C-outsider-reject", ledger_id="outsider_reject"
    )
    public_id = _create_invited_split(
        client, identity, receiver_account_id=receiver_account_id
    )

    resp = client.post(
        f"/api/bill-splits/{public_id}/reject",
        headers=_bearer_for_account_ledger(outsider_account_id, "outsider_reject"),
    )

    assert resp.status_code == 403, resp.json()
    assert resp.json()["error"] == "invitation_not_yours"


def test_cancel_route_rejects_non_sender_account(
    client: TestClient, *, identity
) -> None:
    """Only the sender may cancel; the receiver (a party, but not the sender)
    gets 403. The sender identity check fires before the writer-member lookup,
    so it surfaces as ``invitation_not_yours`` — not a membership error."""
    receiver_account_id = _seed_receiver(
        name="B-cancel-nonsender", ledger_id="receiver_cancel_nonsender"
    )
    public_id = _create_invited_split(
        client, identity, receiver_account_id=receiver_account_id
    )

    resp = client.post(
        f"/api/bill-splits/{public_id}/cancel",
        headers=_bearer_for_account_ledger(
            receiver_account_id, "receiver_cancel_nonsender"
        ),
    )

    assert resp.status_code == 403, resp.json()
    assert resp.json()["error"] == "invitation_not_yours"


def test_accept_by_non_party_forbidden_before_state_is_resolved(
    client: TestClient, *, identity
) -> None:
    """The receiver identity check must fire *before* the settled/expiry
    resolution, so a non-party cannot probe invitation state. Once the real
    receiver has accepted, a non-party accept still gets 403
    ``invitation_not_yours`` — never ``state_conflict`` (which would leak that
    the invitation is already accepted to a different ledger)."""
    receiver_account_id = _seed_receiver(
        name="B-precedence", ledger_id="receiver_precedence"
    )
    outsider_account_id = _seed_receiver(
        name="C-precedence", ledger_id="outsider_precedence"
    )
    public_id = _create_invited_split(
        client, identity, receiver_account_id=receiver_account_id
    )

    accept = client.post(
        f"/api/bill-splits/{public_id}/accept",
        headers=_bearer_for_account_ledger(receiver_account_id, "receiver_precedence"),
        json={"target_ledger_id": "receiver_precedence"},
    )
    assert accept.status_code == 200, accept.json()
    assert accept.json()["status"] == "accepted"

    resp = client.post(
        f"/api/bill-splits/{public_id}/accept",
        headers=_bearer_for_account_ledger(
            outsider_account_id, "outsider_precedence"
        ),
        json={"target_ledger_id": "outsider_precedence"},
    )

    assert resp.status_code == 403, resp.json()
    assert resp.json()["error"] == "invitation_not_yours"
