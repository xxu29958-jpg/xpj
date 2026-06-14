"""ADR-0049 Debt domain slice 3: MemberRepaymentProposal (§3.2 / §5.2 / §11).

Pins the §11 confirmation subset the member repayment-proposal workflow owns. A
``counterparty_type='member'`` Debt has adverse interests (§5): the debtor cannot
unilaterally commit a ``Repayment`` (that would reduce the creditor's receivable),
so the debtor *proposes* "I paid" (a pending intent that never enters the §2 fold)
and the creditor confirms (full or partial), rejects, or the debtor withdraws.
Creating a new proposal supersedes the existing pending one in one transaction;
the ``uq_mrp_one_pending_per_debt`` partial UNIQUE index is the one-pending
backstop (true-concurrency tests live in the ``*_concurrency.py`` real_db lane).

Two distinct authed actors are needed because debtor and creditor must be
different accounts: the ledger owner plus a second member account minted into the
SAME ``owner`` ledger (its own Account + writer LedgerMember + Device + app
AuthToken). A Debt with ``direction='owed_to_me'`` and the member as counterparty
makes the member the debtor (proposer) and the owner the creditor (confirmer);
``direction='i_owe'`` is the mirror.

Fold / lifecycle assertions read the rendered API response (the Debt
``remaining_amount_cents`` / ``row_version`` and the proposal ``status`` /
``confirmed_amount_cents`` / ``committed_repayment_public_id``), never a DB peek —
mirroring slice 1/2. The committed ``Repayment.proposal_id`` back-link is the one
exception read from the DB (it is not exposed in any response).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Account,
    AuthToken,
    Debt,
    Device,
    ExchangeRate,
    LedgerMember,
    MemberRepaymentProposal,
    Repayment,
)
from app.services.identity_service import hash_secret, new_session_token

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _seed_usd_rate(*, tenant_id: str, rate_date: date, rate_to_cny: str) -> None:
    """Seed one USD→CNY rate snapshot (mirrors ``test_debt_repayment._seed_usd_rate``)."""
    with SessionLocal() as db:
        db.add(
            ExchangeRate(
                tenant_id=tenant_id,
                currency_code="USD",
                rate_date=rate_date,
                rate_to_cny=Decimal(rate_to_cny),
                source="manual",
            )
        )
        db.commit()


def _mint_member_actor(*, ledger_id: str = "owner", role: str = "member") -> tuple[int, str]:
    """Create a SECOND authed account in ``ledger_id`` and return (account_id, app_token).

    Models a distinct family member: its own Account, a writer ``LedgerMember``
    row in the same ledger (so it is a writer, not just a bare account), a Device,
    and an app-scope AuthToken — the minimum the auth chain needs to resolve a
    full ``AuthContext`` (account/device/ledger/role) for this actor.
    """
    with SessionLocal() as db:
        account = Account(display_name="家人")
        db.add(account)
        db.flush()
        db.add(
            LedgerMember(ledger_id=ledger_id, account_id=account.id, role=role)
        )
        device = Device(
            account_id=account.id, device_name="pytest-member", platform="android"
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
        return account.id, token


def _member_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_member_debt(
    client: TestClient,
    headers: dict[str, str],
    *,
    direction: str,
    member_account_id: int,
    principal_amount_cents: int = 50000,
) -> dict:
    """Create a member Debt (creator is whoever owns ``headers`` — always the owner).

    ``direction='owed_to_me'`` → debtor=member, creditor=owner (the member proposes,
    the owner confirms). ``direction='i_owe'`` → debtor=owner, creditor=member.
    """
    response = client.post(
        "/api/debts",
        headers=_idem(headers),
        json={
            "direction": direction,
            "counterparty_type": "member",
            "counterparty_account_id": member_account_id,
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_external_debt(
    client: TestClient, headers: dict[str, str], *, principal_amount_cents: int = 50000
) -> dict:
    response = client.post(
        "/api/debts",
        headers=_idem(headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "招商信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _propose(
    client: TestClient,
    headers: dict[str, str],
    debt_public_id: str,
    *,
    proposed_amount_cents: int,
    **extra: object,
):
    return client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals",
        headers=_idem(headers),
        json={"proposed_amount_cents": proposed_amount_cents, **extra},
    )


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


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
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    # Owner directly records a 15000 repayment first (remaining 20000 → 5000).
    direct = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 15000, "expected_row_version": debt["row_version"]},
    )
    assert direct.status_code == 201, direct.json()
    bumped = direct.json()["row_version"]

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
    # The rejected confirm committed NO proposal-linked repayment and left the
    # proposal pending: only the prior direct repayment exists, and no repayment
    # carries this proposal's id.
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


# ── foreign-currency freeze (§2.2) ──────────────────────────────────────────


def _propose_foreign(
    client: TestClient,
    headers: dict[str, str],
    debt_public_id: str,
    *,
    original_currency_code: str,
    original_amount: str,
    paid_at: str,
):
    """Create a foreign-currency proposal (no proposed_amount_cents — the two
    amount inputs are mutually exclusive; the backend freezes the home amount)."""
    return client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals",
        headers=_idem(headers),
        json={
            "original_currency_code": original_currency_code,
            "original_amount": original_amount,
            "paid_at": paid_at,
        },
    )


def test_foreign_currency_proposal_freezes_home_cents_and_provenance(
    client: TestClient, *, identity
) -> None:
    # §2.2: a foreign-currency proposal freezes a backend-authoritative home
    # proposed_amount_cents from the [[0027]] snapshot + keeps original provenance.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id,
        principal_amount_cents=100000,
    )
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    response = _propose_foreign(
        client,
        _member_headers(member_token),
        debt["public_id"],
        original_currency_code="USD",
        original_amount="100.00",
        paid_at="2026-05-10T04:00:00Z",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    # 100 USD * 7.2 = 720.00 CNY → 72000 home cents frozen.
    assert body["proposed_amount_cents"] == 72000
    assert body["home_currency_code"] == "CNY"
    assert body["original_currency_code"] == "USD"
    assert body["original_amount_minor"] == 10000  # 100.00 USD → 10000 minor units


def test_foreign_currency_full_confirm_copies_provenance_onto_repayment(
    client: TestClient, *, identity
) -> None:
    # §3.2: a FULL confirm copies the proposal's original-currency provenance onto
    # the committed Repayment.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id,
        principal_amount_cents=100000,
    )
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    proposal = _propose_foreign(
        client,
        _member_headers(member_token),
        debt["public_id"],
        original_currency_code="USD",
        original_amount="100.00",
        paid_at="2026-05-10T04:00:00Z",
    ).json()

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},  # None → full confirm
    )
    assert confirm.status_code == 201, confirm.json()
    assert confirm.json()["remaining_amount_cents"] == 28000  # 100000 - 72000

    # DB-peek: the committed Repayment carries the original-currency provenance.
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        repayment = db.scalar(select(Repayment).where(Repayment.debt_id == debt_row.id))
        assert repayment.amount_cents == 72000
        assert repayment.original_currency_code == "USD"
        assert repayment.original_amount_minor == 10000


def test_foreign_currency_partial_confirm_lands_home_only(client: TestClient, *, identity) -> None:
    # §3.2: a PARTIAL confirm records a home-only Repayment (original_* NULL — a
    # partial home amount has no faithful original-currency split).
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id,
        principal_amount_cents=100000,
    )
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    proposal = _propose_foreign(
        client,
        _member_headers(member_token),
        debt["public_id"],
        original_currency_code="USD",
        original_amount="100.00",
        paid_at="2026-05-10T04:00:00Z",
    ).json()

    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"confirmed_amount_cents": 50000, "expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 201, confirm.json()
    assert confirm.json()["remaining_amount_cents"] == 50000  # 100000 - 50000

    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        repayment = db.scalar(select(Repayment).where(Repayment.debt_id == debt_row.id))
        assert repayment.amount_cents == 50000
        assert repayment.original_currency_code is None
        assert repayment.original_amount_minor is None


def test_foreign_currency_proposal_pending_rate_is_409(client: TestClient, *, identity) -> None:
    # §2.2: a foreign-currency proposal whose rate is not available cannot freeze a
    # home amount → exchange_rate_pending (409); no proposal row is created.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id,
        principal_amount_cents=100000,
    )
    # No USD rate seeded for that paid_at date → cannot freeze → 409.
    response = _propose_foreign(
        client,
        _member_headers(member_token),
        debt["public_id"],
        original_currency_code="USD",
        original_amount="50.00",
        paid_at="2026-05-10T04:00:00Z",
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "exchange_rate_pending"
    # No proposal landed.
    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert proposals == []


# ── adverse-interest party guards ───────────────────────────────────────────


def test_creditor_cannot_create_proposal_debtor_only(client: TestClient, *, identity) -> None:
    # §11 / §5.2: only the debtor may propose. Owner is the creditor here
    # (owed_to_me → member owes owner), so the owner proposing is 403.
    member_id, _member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    response = _propose(
        client, identity.app_headers, debt["public_id"], proposed_amount_cents=10000
    )
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "repayment_proposal_debtor_only"


def test_creditor_cannot_withdraw_proposal_debtor_only(client: TestClient, *, identity) -> None:
    # §5.2: only the debtor may withdraw their own proposal.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    # Owner (creditor) tries to withdraw → 403.
    withdraw = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/withdraw",
        headers=_idem(identity.app_headers),
        json={},
    )
    assert withdraw.status_code == 403, withdraw.json()
    assert withdraw.json()["error"] == "repayment_proposal_debtor_only"


def test_debtor_cannot_confirm_proposal_creditor_only(client: TestClient, *, identity) -> None:
    # §11 / §5.2: only the creditor may confirm. Member is the debtor here, so
    # the member confirming their own proposal is 403.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(_member_headers(member_token)),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 403, confirm.json()
    assert confirm.json()["error"] == "repayment_proposal_creditor_only"


def test_debtor_cannot_reject_proposal_creditor_only(client: TestClient, *, identity) -> None:
    # §5.2: only the creditor may reject.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    reject = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/reject",
        headers=_idem(_member_headers(member_token)),
        json={},
    )
    assert reject.status_code == 403, reject.json()
    assert reject.json()["error"] == "repayment_proposal_creditor_only"


# ── viewer 403 / unauth 401 on every write route ────────────────────────────


def test_viewer_cannot_create_proposal(client: TestClient, *, identity) -> None:
    # §11: viewer cannot create/repay/adjust/void/link Debt — proposal create too.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="i_owe", member_account_id=member_id
    )
    # Demote the member (the debtor for i_owe is the owner; demote the member's
    # own ledger role so the member token is viewer when it acts).
    with SessionLocal() as db:
        row = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.account_id == member_id)
            .limit(1)
        )
        row.role = "viewer"
        db.commit()
    # The (now-viewer) member tries any write on this Debt's proposal surface.
    response = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=10000
    )
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "permission_denied"
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_viewer_cannot_confirm_proposal(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    # Owner (creditor) is demoted to viewer → confirm is 403 before any business.
    _set_owner_ledger_role("viewer")
    confirm = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 403, confirm.json()
    assert confirm.json()["error"] == "permission_denied"


def test_viewer_cannot_reject_proposal(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    _set_owner_ledger_role("viewer")
    reject = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/reject",
        headers=_idem(identity.app_headers),
        json={},
    )
    assert reject.status_code == 403, reject.json()
    assert reject.json()["error"] == "permission_denied"


def test_viewer_cannot_withdraw_proposal(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    # Demote the member (debtor) to viewer → withdraw is 403.
    with SessionLocal() as db:
        row = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.account_id == member_id)
            .limit(1)
        )
        row.role = "viewer"
        db.commit()
    withdraw = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/withdraw",
        headers=_idem(_member_headers(member_token)),
        json={},
    )
    assert withdraw.status_code == 403, withdraw.json()
    assert withdraw.json()["error"] == "permission_denied"


def test_create_proposal_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    member_id, _member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={"proposed_amount_cents": 10000},
    )
    assert response.status_code == 401


def test_confirm_proposal_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={"expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 401


def test_withdraw_proposal_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/withdraw",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={},
    )
    assert response.status_code == 401


def test_reject_proposal_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/reject",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={},
    )
    assert response.status_code == 401


# ── idempotency contract on the create + confirm surfaces ───────────────────


def test_create_proposal_idempotent_replay_applies_once(client: TestClient, *, identity) -> None:
    # §11: idempotency fingerprint fields are canonicalized and stable for the
    # proposal flow; same key + same fingerprint → the same proposal, applied once.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    key = str(uuid4())
    headers = {**_member_headers(member_token), "Idempotency-Key": key}
    payload = {"proposed_amount_cents": 20000}

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=headers, json=payload
    )
    assert first.status_code == 201, first.json()
    proposal_public_id = first.json()["public_id"]

    replay = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=headers, json=payload
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == proposal_public_id  # same row, not a 2nd

    # Exactly one proposal exists (no second pending created, no supersede chain).
    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert len(proposals) == 1
    assert proposals[0]["supersedes_proposal_public_id"] is None


def test_create_proposal_reused_key_different_fingerprint_is_422(
    client: TestClient, *, identity
) -> None:
    # §11: idempotency key reused with a different fingerprint is rejected.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    key = str(uuid4())
    headers = {**_member_headers(member_token), "Idempotency-Key": key}
    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=headers,
        json={"proposed_amount_cents": 20000},
    )
    assert first.status_code == 201, first.json()
    mismatch = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=headers,
        json={"proposed_amount_cents": 99999},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"] == "idempotency_key_reused"


def test_create_proposal_missing_idempotency_key_is_422(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=_member_headers(member_token),  # no Idempotency-Key
        json={"proposed_amount_cents": 20000},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_required"


def test_confirm_idempotent_replay_changes_remaining_once(client: TestClient, *, identity) -> None:
    # §11: retry with same key/fingerprint changes remaining once; the parent
    # Debt is not bumped a second time (§2.1 replay does not bump).
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    payload = {"expected_row_version": debt["row_version"]}

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 201, first.json()
    assert first.json()["remaining_amount_cents"] == 30000
    bumped = first.json()["row_version"]

    replay = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["remaining_amount_cents"] == 30000  # once, not 10000
    assert replay.json()["row_version"] == bumped  # no second bump

    # Authoritative: exactly one Repayment exists.
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        repayments = list(
            db.scalars(select(Repayment).where(Repayment.debt_id == debt_row.id))
        )
        assert len(repayments) == 1


def test_confirm_missing_idempotency_key_is_422(client: TestClient, *, identity) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=identity.app_headers,  # no Idempotency-Key
        json={"expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_required"


def test_confirm_same_key_different_expected_row_version_is_reused(
    client: TestClient, *, identity
) -> None:
    # §3.6: ``expected_row_version`` is part of the [[0042]] fingerprint, so the
    # SAME Idempotency-Key replayed with a DIFFERENT expected_row_version is a key
    # reuse (a new intent must use a new key), not an idempotent replay.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=headers,
        json={"expected_row_version": debt["row_version"]},
    )
    assert first.status_code == 201, first.json()

    mismatch = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=headers,  # same key K
        json={"expected_row_version": debt["row_version"] + 1},  # different expected version
    )
    assert mismatch.status_code == 422, mismatch.json()
    assert mismatch.json()["error"] == "idempotency_key_reused"


# ── adverse-interest no-clobber: a resolving write cannot overwrite a confirm ──
# §2.1 / §3.2: confirm/withdraw/reject of the SAME proposal serialise on the
# proposal row via a guarded ``UPDATE ... WHERE status='pending'`` (only confirm
# also holds the parent-Debt lock). A debtor withdraw / creditor reject that lands
# AFTER the proposal was already confirmed must fail ``not_pending`` and leave the
# committed Repayment + reduced remaining untouched — never silently clobber it.


def test_withdraw_after_confirm_is_rejected_not_pending(
    client: TestClient, *, identity
) -> None:
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

    # Debtor tries to withdraw the now-confirmed proposal → rejected, no clobber.
    withdraw = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/withdraw",
        headers=_idem(_member_headers(member_token)),
        json={},
    )
    assert withdraw.status_code == 409, withdraw.json()
    assert withdraw.json()["error"] == "repayment_proposal_not_pending"

    # The confirm survived intact: proposal still confirmed, fold still reduced once.
    items = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "confirmed"
    assert items[0]["committed_repayment_public_id"] is not None
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["remaining_amount_cents"] == 30000
    assert detail["row_version"] == debt["row_version"] + 1
    with SessionLocal() as db:
        debt_id = db.scalar(select(Debt.id).where(Debt.public_id == debt["public_id"]))
        repayments = db.scalars(select(Repayment).where(Repayment.debt_id == debt_id)).all()
    assert len(repayments) == 1


def test_reject_after_confirm_is_rejected_not_pending(
    client: TestClient, *, identity
) -> None:
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

    # Creditor tries to reject the now-confirmed proposal → rejected, no clobber.
    reject = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/reject",
        headers=_idem(identity.app_headers),
        json={},
    )
    assert reject.status_code == 409, reject.json()
    assert reject.json()["error"] == "repayment_proposal_not_pending"

    items = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "confirmed"
