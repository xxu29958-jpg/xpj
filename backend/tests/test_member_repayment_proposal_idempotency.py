"""ADR-0049 member repayment proposal idempotency and no-clobber tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Debt, Repayment
from tests.debt_proposal_helpers import (
    _create_member_debt,
    _idem,
    _member_headers,
    _mint_member_actor,
    _propose,
)

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


def test_create_proposal_replay_normalizes_note_and_datetimes(
    client: TestClient, *, identity
) -> None:
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    key = str(uuid4())
    headers = {**_member_headers(member_token), "Idempotency-Key": key}

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=headers,
        json={
            "proposed_amount_cents": 20000,
            "note": " paid ",
            "paid_at": "2026-05-10T08:00:00+08:00",
            "expires_at": "2026-06-10T00:00:00+08:00",
        },
    )
    assert first.status_code == 201, first.json()

    replay = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=headers,
        json={
            "proposed_amount_cents": 20000,
            "note": "paid",
            "paid_at": "2026-05-10T00:00:00Z",
            "expires_at": "2026-06-09T16:00:00Z",
        },
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == first.json()["public_id"]
    assert replay.json()["note"] == "paid"


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


def test_confirm_replay_under_different_debt_is_422(
    client: TestClient, *, identity
) -> None:
    member_id, member_token = _mint_member_actor()
    debt_a = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    debt_b = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    proposal = _propose(
        client, _member_headers(member_token), debt_a["public_id"], proposed_amount_cents=20000
    ).json()
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    payload = {"expected_row_version": debt_a["row_version"]}

    first = client.post(
        f"/api/debts/{debt_a['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 201, first.json()

    mismatch = client.post(
        f"/api/debts/{debt_b['public_id']}/repayment-proposals/{proposal['public_id']}/confirm",
        headers=headers,
        json=payload,
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"] == "idempotency_key_reused"


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


def test_create_proposal_same_key_different_debt_is_reused(
    client: TestClient, *, identity
) -> None:
    # §3.6: the create fingerprint targets the PARENT debt public_id, so the same
    # Idempotency-Key + same body against a DIFFERENT member debt is rejected
    # idempotency_key_reused — not a cross-debt HIT that would try to serialise
    # debt A's proposal under debt B.
    member_id, member_token = _mint_member_actor()
    debt_a = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    debt_b = _create_member_debt(
        client, identity.app_headers, direction="owed_to_me", member_account_id=member_id
    )
    key = str(uuid4())
    body = {"proposed_amount_cents": 20000}
    first = client.post(
        f"/api/debts/{debt_a['public_id']}/repayment-proposals",
        headers={**_member_headers(member_token), "Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 201, first.json()
    second = client.post(
        f"/api/debts/{debt_b['public_id']}/repayment-proposals",
        headers={**_member_headers(member_token), "Idempotency-Key": key},
        json=body,
    )
    assert second.status_code == 422, second.json()
