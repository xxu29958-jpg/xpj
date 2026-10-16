"""ADR-0049 §5.2 slice-5 account-scoped cross-ledger participant confirm/reject.

A bill-split member Debt is owned by the RECEIVER's ledger with the SENDER as
the creditor (``direction='i_owe'``, ``owner_account_id=receiver``,
``counterparty_account_id=sender``). Before slice 5 the repayment confirm/reject
path was ledger-scoped, so a creditor who is not a member of the receiver's
ledger could not confirm or clear the obligation — the §0.1 hard boundary that
kept ``DEBT_ROLLOUT_ENABLED`` off.

Slice 5 resolves the Debt by participant identity (debtor OR creditor account)
unioned with ledger membership, so:

- the creditor who IS a member of a shared target ledger confirms as before
  (full response, ledger id kept);
- the creditor who is NOT a member of the receiver's private ledger confirms
  cross-ledger and gets only the Debt shell (ledger id redacted, §5.2);
- a non-participant gets ``debt_not_found`` (cross-ledger existence hiding).

These drive the real route layer over HTTP (auth + idempotency + the participant
scope), which is exactly where the old ledger scope lived.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Debt,
    LedgerMember,
    Repayment,
)
from tests._infra.identity import seeded_owner_account_id
from tests._runtime_protocol import current_protocol_headers

# Reuse the slice-4 linkage helpers (owner expense → invite → service-level accept).
from tests.bill_split_test_support import _accept_into, _debt_public_id_for, _mint_app_token, _seed_personal_ledger
from tests.bill_split_test_support import _create_invited_split as _invite


@pytest.fixture
def debt_rollout_on(monkeypatch: pytest.MonkeyPatch):
    """Enable the §4 bill-split → Debt linkage for the test."""
    monkeypatch.setenv("DEBT_ROLLOUT_ENABLED", "true")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _add_member(*, ledger_id: str, account_id: int, role: str = "member") -> None:
    with SessionLocal() as db:
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account_id, role=role))
        db.commit()


def _headers(token: str) -> dict[str, str]:
    return current_protocol_headers({"Authorization": f"Bearer {token}"})


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _propose(
    client: TestClient, token: str, debt_public_id: str, *, proposed_amount_cents: int
) -> dict:
    resp = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals",
        headers=_idem(_headers(token)),
        json={"proposed_amount_cents": proposed_amount_cents},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


# ── ② non-member creditor: cross-ledger confirm clears the Debt (shell only) ──


def test_cross_ledger_creditor_confirms_and_clears_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # The §5.2 core: the sender (creditor) is NOT a member of the receiver's
    # PRIVATE ledger, yet can confirm the debtor's repayment proposal and clear
    # the obligation. The response is the Debt shell — ledger id redacted.
    owner_id = seeded_owner_account_id()
    receiver_id = _seed_personal_ledger(name="B-priv", ledger_id="receiver_priv")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_priv")
    debt_public_id = _debt_public_id_for(public_id)

    # Debtor (receiver, owner of their private ledger) proposes "I paid" the full share.
    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="receiver_priv")
    proposal = _propose(client, receiver_token, debt_public_id, proposed_amount_cents=2500)
    assert proposal["status"] == "pending"

    # Creditor (the owner/sender) reads the Debt cross-ledger via their OWN ledger
    # token: participant scope finds it, but the shell redacts the receiver's ledger.
    detail = client.get(f"/api/debts/{debt_public_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    shell = detail.json()
    assert shell["ledger_id"] is None  # §5.2 cross-ledger shell: no counterparty ledger
    assert shell["counterparty_account_id"] == owner_id  # the creditor is the counterparty
    assert shell["principal_amount_cents"] == 2500
    assert shell["remaining_amount_cents"] == 2500
    assert shell["status"] == "open"
    row_version = shell["row_version"]

    # Creditor confirms cross-ledger → commits the repayment, remaining folds to 0.
    confirm = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": row_version},
    )
    assert confirm.status_code == 201, confirm.json()
    body = confirm.json()
    assert body["ledger_id"] is None  # still shell for the cross-ledger creditor
    assert body["remaining_amount_cents"] == 0
    assert body["paid_amount_cents"] == 2500
    assert body["status"] == "cleared"
    assert body["row_version"] == row_version + 1

    # Authoritative DB state: cleared, exactly one repayment for the full share.
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        assert debt.status == "cleared"
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert len(repayments) == 1
        assert repayments[0].amount_cents == 2500


def test_cross_ledger_creditor_rejects_proposal(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # §5.2: a non-member creditor can also REJECT a proposal cross-ledger; the
    # fold is untouched (no repayment) and the proposal latches 'rejected'.
    receiver_id = _seed_personal_ledger(name="B-rej", ledger_id="receiver_rejx")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_rejx")
    debt_public_id = _debt_public_id_for(public_id)

    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="receiver_rejx")
    proposal = _propose(client, receiver_token, debt_public_id, proposed_amount_cents=2500)

    reject = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals/{proposal['public_id']}/reject",
        headers=_idem(identity.app_headers),
        json={},
    )
    assert reject.status_code == 201, reject.json()
    assert reject.json()["status"] == "rejected"

    # Remaining unchanged (still the full principal); the creditor sees the shell.
    detail = client.get(f"/api/debts/{debt_public_id}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 2500
    assert detail.json()["status"] == "open"


def test_cross_ledger_creditor_lists_pending_proposal(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # The creditor must be able to SEE the pending proposal awaiting confirmation
    # even though the Debt lives in the receiver's private ledger (§5.2 read union).
    receiver_id = _seed_personal_ledger(name="B-list", ledger_id="receiver_listx")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_listx")
    debt_public_id = _debt_public_id_for(public_id)

    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="receiver_listx")
    proposal = _propose(client, receiver_token, debt_public_id, proposed_amount_cents=2500)

    listing = client.get(
        f"/api/debts/{debt_public_id}/repayment-proposals", headers=identity.app_headers
    )
    assert listing.status_code == 200, listing.json()
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["public_id"] == proposal["public_id"]
    assert items[0]["status"] == "pending"


# ── ① member case: creditor IS a member of a shared target ledger ────────────


def test_member_creditor_in_shared_ledger_settles_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # When the receiver accepts into a SHARED ledger the sender is also a member
    # of, the creditor confirms AS A MEMBER — the same-ledger path. The response
    # keeps the ledger id (not redacted), proving the union's member branch.
    owner_id = seeded_owner_account_id()
    receiver_id = _seed_personal_ledger(name="M", ledger_id="shared_m")
    _add_member(ledger_id="shared_m", account_id=owner_id, role="member")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "shared_m")
    debt_public_id = _debt_public_id_for(public_id)

    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="shared_m")
    owner_shared_token = _mint_app_token(account_id=owner_id, ledger_id="shared_m")

    proposal = _propose(client, receiver_token, debt_public_id, proposed_amount_cents=2500)

    detail = client.get(f"/api/debts/{debt_public_id}", headers=_headers(owner_shared_token))
    assert detail.status_code == 200, detail.json()
    assert detail.json()["ledger_id"] == "shared_m"  # member branch keeps the ledger id
    # §3.2: the SAME-LEDGER creditor — viewer_is_debtor is False even though ledger_id is non-null.
    # A client must not derive the role from ledger membership: this member-of-the-Debt's-ledger
    # account is the counterparty (creditor), not the owner/debtor.
    assert detail.json()["viewer_is_debtor"] is False
    row_version = detail.json()["row_version"]

    confirm = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(_headers(owner_shared_token)),
        json={"expected_row_version": row_version},
    )
    assert confirm.status_code == 201, confirm.json()
    body = confirm.json()
    assert body["ledger_id"] == "shared_m"  # full response for a ledger member
    assert body["remaining_amount_cents"] == 0
    assert body["status"] == "cleared"
    assert body["row_version"] == row_version + 1


# ── §3.2 server-authoritative viewer role ────────────────────────────────────


def test_viewer_is_debtor_role_for_both_parties(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # The server is the authority for the debtor/creditor role the client renders (the client can't
    # derive it). The bill-split Debt is owned by the receiver (debtor, direction i_owe) with the
    # sender (identity) as the creditor.
    receiver_id = _seed_personal_ledger(name="B-role", ledger_id="receiver_role")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_role")
    debt_public_id = _debt_public_id_for(public_id)

    # Debtor (receiver, owner of the Debt's ledger) → viewer_is_debtor True.
    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="receiver_role")
    debtor_view = client.get(f"/api/debts/{debt_public_id}", headers=_headers(receiver_token))
    assert debtor_view.status_code == 200, debtor_view.json()
    assert debtor_view.json()["viewer_is_debtor"] is True

    # Creditor (sender, identity) reading cross-ledger → viewer_is_debtor False (and shell-redacted).
    creditor_view = client.get(f"/api/debts/{debt_public_id}", headers=identity.app_headers)
    assert creditor_view.status_code == 200, creditor_view.json()
    assert creditor_view.json()["viewer_is_debtor"] is False
    assert creditor_view.json()["ledger_id"] is None


# ── non-participant existence hiding ─────────────────────────────────────────


def test_non_participant_cannot_see_or_confirm_cross_ledger_debt(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # A third account, neither debtor nor creditor and not a member of the Debt's
    # ledger, gets debt_not_found (404) — cross-ledger existence hiding, no leak.
    receiver_id = _seed_personal_ledger(name="B-hide", ledger_id="receiver_hide")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_hide")
    debt_public_id = _debt_public_id_for(public_id)

    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="receiver_hide")
    proposal = _propose(client, receiver_token, debt_public_id, proposed_amount_cents=2500)

    stranger_id = _seed_personal_ledger(name="C", ledger_id="stranger_c")
    stranger_token = _mint_app_token(account_id=stranger_id, ledger_id="stranger_c")

    # Read is hidden.
    detail = client.get(f"/api/debts/{debt_public_id}", headers=_headers(stranger_token))
    assert detail.status_code == 404, detail.json()
    assert detail.json()["error"] == "debt_not_found"

    # Listing proposals is hidden.
    listing = client.get(
        f"/api/debts/{debt_public_id}/repayment-proposals", headers=_headers(stranger_token)
    )
    assert listing.status_code == 404, listing.json()

    # Confirm is hidden (the preflight proposal read 404s before any business).
    confirm = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(_headers(stranger_token)),
        json={"expected_row_version": 1},
    )
    assert confirm.status_code == 404, confirm.json()
    assert confirm.json()["error"] == "debt_not_found"

    # Nothing committed: the proposal is still pending, the Debt still open.
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt is not None
        assert debt.status == "open"
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert repayments == []


def test_cross_ledger_confirm_is_idempotent_on_replay(
    client: TestClient, *, identity, debt_rollout_on
) -> None:
    # The cross-ledger creditor's confirm carries an Idempotency-Key scoped to the
    # creditor's OWN ledger; a lost-response replay returns the canonical cleared
    # Debt and commits exactly one repayment (no second fold change).
    receiver_id = _seed_personal_ledger(name="B-idem", ledger_id="receiver_idemx")
    public_id = _invite(client, identity, receiver_id, amount_cents=2500)
    _accept_into(public_id, receiver_id, "receiver_idemx")
    debt_public_id = _debt_public_id_for(public_id)

    receiver_token = _mint_app_token(account_id=receiver_id, ledger_id="receiver_idemx")
    proposal = _propose(client, receiver_token, debt_public_id, proposed_amount_cents=2500)

    key = str(uuid4())
    url = (
        f"/api/debts/{debt_public_id}/repayment-proposals/"
        f"{proposal['public_id']}/confirm"
    )
    first = client.post(
        url,
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": 1},
    )
    assert first.status_code == 201, first.json()
    assert first.json()["remaining_amount_cents"] == 0

    replay = client.post(
        url,
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"expected_row_version": 1},
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["remaining_amount_cents"] == 0
    assert replay.json()["ledger_id"] is None  # replay re-serialises the shell too

    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == debt.id)))
        assert len(repayments) == 1  # exactly one fold change despite the replay
