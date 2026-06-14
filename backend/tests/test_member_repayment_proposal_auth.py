"""ADR-0049 member repayment proposal authorization tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests.debt_proposal_helpers import (
    VIEWER_WRITE_MESSAGE,
    _create_member_debt,
    _idem,
    _member_headers,
    _mint_member_actor,
    _propose,
    _set_owner_ledger_role,
)


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


def test_reject_note_is_rejected_not_silently_dropped(
    client: TestClient, *, identity
) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=20000
    ).json()
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/reject",
        headers=_idem(identity.app_headers),
        json={"note": "I did not receive this payment"},
    )
    assert response.status_code == 422
    items = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert items[0]["status"] == "pending"


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


