"""ADR-0049 member repayment proposal lifecycle tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Debt, MemberRepaymentProposal, Repayment
from tests.debt_proposal_helpers import (
    _create_external_debt,
    _create_member_debt,
    _idem,
    _member_headers,
    _mint_member_actor,
    _propose,
)

# ── happy path: debtor proposes, creditor confirms ──────────────────────────


def test_debtor_can_create_pending_proposal(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    # Member is the debtor (owed_to_me → counterparty owes the owner).
    response = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "pending"
    assert body["proposed_amount_cents"] == 20000
    assert body["confirmed_amount_cents"] is None
    assert body["debt_public_id"] == debt["public_id"]
    assert body["supersedes_proposal_public_id"] is None
    assert body["committed_repayment_public_id"] is None
    assert body["public_id"]
    # The 30-day TTL is latched by value: expires_at − created_at ≈ 30 days
    # (small tolerance for the few-ms gap between the two now_utc() reads).
    created = datetime.fromisoformat(body["created_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert abs((expires - created) - timedelta(days=30)) < timedelta(seconds=5)


def test_pending_proposal_does_not_reduce_remaining(client: TestClient, *, identity) -> None:
    # §11: debtor-only repayment proposal does not reduce remaining.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    )
    assert proposal.status_code == 201, proposal.json()
    # The fold is unchanged: a pending proposal is an intent, not a fact.
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 50000
    assert detail.json()["row_version"] == debt["row_version"]


def test_creditor_full_confirm_commits_repayment_exactly_once(
    client: TestClient, *, identity
) -> None:
    # §11: creditor confirmation commits a debtor repayment proposal exactly once;
    # remaining decreases once; the committed Repayment.proposal_id links back.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
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
    body = confirm.json()  # confirm replies with the fold-after DebtResponse
    assert body["remaining_amount_cents"] == 30000  # 50000 - 20000
    assert body["paid_amount_cents"] == 20000
    assert body["status"] == "open"
    assert body["row_version"] == debt["row_version"] + 1  # parent bumped once

    # Proposal latched confirmed; back-link to the committed repayment present.
    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert len(proposals) == 1
    assert proposals[0]["status"] == "confirmed"
    assert proposals[0]["confirmed_amount_cents"] == 20000
    committed_public_id = proposals[0]["committed_repayment_public_id"]
    assert committed_public_id is not None

    # Exactly one Repayment, linked back via proposal_id (the only DB-only assert).
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        repayments = list(
            db.scalars(select(Repayment).where(Repayment.debt_id == debt_row.id))
        )
        assert len(repayments) == 1
        assert repayments[0].amount_cents == 20000
        assert repayments[0].public_id == committed_public_id
        proposal_row = db.scalar(
            select(MemberRepaymentProposal).where(
                MemberRepaymentProposal.public_id == proposal["public_id"]
            )
        )
        assert repayments[0].proposal_id == proposal_row.id


def test_creditor_partial_confirm_commits_only_confirmed_amount(
    client: TestClient, *, identity
) -> None:
    # §11: creditor partial confirmation commits only the confirmed amount and
    # closes the proposal (partially_confirmed).
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"confirmed_amount_cents": 12000, "expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 201, confirm.json()
    body = confirm.json()
    assert body["remaining_amount_cents"] == 38000  # 50000 - 12000, only confirmed
    assert body["paid_amount_cents"] == 12000

    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert proposals[0]["status"] == "partially_confirmed"
    assert proposals[0]["confirmed_amount_cents"] == 12000
    committed_public_id = proposals[0]["committed_repayment_public_id"]
    assert committed_public_id is not None
    # DB-peek: exactly one linked Repayment of the confirmed (partial) amount, with
    # original-currency provenance NULL (a partial home amount has no faithful
    # original-currency split, §3.2) and proposal_id linked back to the proposal.
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        proposal_row = db.scalar(
            select(MemberRepaymentProposal).where(
                MemberRepaymentProposal.public_id == proposal["public_id"]
            )
        )
        repayments = list(
            db.scalars(select(Repayment).where(Repayment.debt_id == debt_row.id))
        )
        assert len(repayments) == 1
        repayment = repayments[0]
        assert repayment.amount_cents == 12000
        assert repayment.public_id == committed_public_id
        assert repayment.original_currency_code is None
        assert repayment.proposal_id == proposal_row.id


def test_owner_debtor_member_creditor_direction_i_owe(client: TestClient, *, identity) -> None:
    # Mirror direction: owner owes the member → owner proposes, member confirms.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="i_owe", member_account_id=member_id
    )
    # Owner is the debtor here.
    proposal = _propose(
        client, identity.app_headers, debt["public_id"], proposed_amount_cents=15000
    )
    assert proposal.status_code == 201, proposal.json()
    # Member (creditor) confirms.
    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal.json()['public_id']}/confirm",
        headers=_idem(_member_headers(member_token)),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 201, confirm.json()
    assert confirm.json()["remaining_amount_cents"] == 35000


# ── supersede / one-pending invariant ───────────────────────────────────────


def test_replacement_create_supersedes_previous_pending(client: TestClient, *, identity) -> None:
    # §11: creating a replacement proposal supersedes the previous pending one
    # instead of leaving both confirmable; only one pending remains.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    second = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=25000
    ).json()

    # New one links back to the one it superseded.
    assert second["supersedes_proposal_public_id"] == first["public_id"]
    assert second["status"] == "pending"

    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    by_id = {p["public_id"]: p for p in proposals}
    assert by_id[first["public_id"]]["status"] == "superseded"
    assert by_id[second["public_id"]]["status"] == "pending"
    # Exactly one pending across the Debt (the partial-index invariant, observably).
    assert sum(1 for p in proposals if p["status"] == "pending") == 1


def test_changing_amount_creates_superseding_proposal_not_inplace_edit(
    client: TestClient, *, identity
) -> None:
    # §11: changing a pending proposal amount creates a superseding proposal
    # rather than editing in place — the old row is preserved, a new id appears.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    second = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=30000
    ).json()

    assert second["public_id"] != first["public_id"]  # new row, not in-place
    assert second["proposed_amount_cents"] == 30000
    # The original row still carries its original (unedited) amount.
    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    by_id = {p["public_id"]: p for p in proposals}
    assert by_id[first["public_id"]]["proposed_amount_cents"] == 20000
    assert by_id[first["public_id"]]["status"] == "superseded"


def test_proposal_on_external_debt_requires_member_debt(client: TestClient, *, identity) -> None:
    # §11 / §3.2: a proposal only applies to a member Debt; external is refused.
    debt = _create_external_debt(client, identity.app_headers)
    response = _propose(
        client, identity.app_headers, debt["public_id"], proposed_amount_cents=10000
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "repayment_proposal_requires_member_debt"


# ── withdraw ────────────────────────────────────────────────────────────────


def test_debtor_can_withdraw_pending_proposal_remaining_unchanged(
    client: TestClient, *, identity
) -> None:
    # §11: debtor can withdraw a pending proposal without changing remaining.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()

    withdraw = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/withdraw",
        headers=_idem(_member_headers(member_token)),
        json={},
    )
    assert withdraw.status_code == 201, withdraw.json()
    assert withdraw.json()["status"] == "withdrawn"

    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 50000  # unchanged
    assert detail.json()["row_version"] == debt["row_version"]  # no fold change


# ── terminal states cannot be confirmed ─────────────────────────────────────


def test_superseded_proposal_cannot_be_confirmed(client: TestClient, *, identity) -> None:
    # §11: superseded proposals cannot be confirmed.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=25000
    )  # supersedes `first`

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{first['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 409, confirm.json()
    assert confirm.json()["error"] == "repayment_proposal_not_pending"
    # And remaining did not move.
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 50000


def test_withdrawn_proposal_cannot_be_confirmed(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/withdraw",
        headers=_idem(_member_headers(member_token)),
        json={},
    )

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 409, confirm.json()
    assert confirm.json()["error"] == "repayment_proposal_not_pending"


def test_rejected_proposal_cannot_be_confirmed_and_remaining_unchanged(
    client: TestClient, *, identity
) -> None:
    # §11: expired/rejected/withdrawn/superseded proposals do not reduce remaining.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    reject = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/reject",
        headers=_idem(identity.app_headers),
        json={"note": "金额对不上"},
    )
    assert reject.status_code == 201, reject.json()
    assert reject.json()["status"] == "rejected"

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 409, confirm.json()
    assert confirm.json()["error"] == "repayment_proposal_not_pending"
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 50000


def test_expired_proposal_cannot_be_confirmed(client: TestClient, *, identity) -> None:
    # §11: expired proposals do not reduce remaining / cannot be confirmed.
    # Stage expiry by submitting an explicit past ``expires_at`` on create.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client,
        _member_headers(member_token),
        debt["public_id"],
        proposed_amount_cents=20000,
        expires_at="2020-01-01T00:00:00Z",
    ).json()

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 409, confirm.json()
    assert confirm.json()["error"] == "repayment_proposal_expired"
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 50000


# ── confirm amount guards ───────────────────────────────────────────────────


def test_confirm_overpay_is_rejected(client: TestClient, *, identity) -> None:
    # §11: repayment exceeding remaining is rejected (debt_overpay_rejected).
    # Drive remaining below the proposed amount with a prior direct repayment,
    # then a full confirm of the proposal would overpay.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id,
        principal_amount_cents=20000,
    )
    first = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=15000
    ).json()
    first_confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{first['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert first_confirm.status_code == 201, first_confirm.json()
    bumped = first_confirm.json()["row_version"]

    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": bumped},
    )
    assert confirm.status_code == 422, confirm.json()
    assert confirm.json()["error"] == "debt_overpay_rejected"
    # Remaining held at 5000 (only the direct repayment landed).
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 5000
    # The rejected confirm committed NO repayment for the second proposal and left
    # it pending; only the prior confirmed proposal reduced the remaining amount.
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        proposal_row = db.scalar(
            select(MemberRepaymentProposal).where(
                MemberRepaymentProposal.public_id == proposal["public_id"]
            )
        )
        assert proposal_row.status == "pending"
        linked = list(
            db.scalars(
                select(Repayment)
                .where(Repayment.debt_id == debt_row.id)
                .where(Repayment.proposal_id == proposal_row.id)
            )
        )
        assert linked == []


def test_confirm_amount_above_proposed_is_rejected(client: TestClient, *, identity) -> None:
    # §11: confirming above the proposed amount is invalid (the creditor cannot
    # inflate the debtor's proposal) → repayment_proposal_amount_invalid.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"confirmed_amount_cents": 25000, "expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 422, confirm.json()
    assert confirm.json()["error"] == "repayment_proposal_amount_invalid"
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 50000
    # The rejected confirm committed NO repayment at all and left the proposal pending.
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        proposal_row = db.scalar(
            select(MemberRepaymentProposal).where(
                MemberRepaymentProposal.public_id == proposal["public_id"]
            )
        )
        assert proposal_row.status == "pending"
        repayments = list(
            db.scalars(select(Repayment).where(Repayment.debt_id == debt_row.id))
        )
        assert repayments == []
