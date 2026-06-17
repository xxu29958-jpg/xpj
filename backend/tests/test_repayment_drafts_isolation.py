"""ADR-0049 §杠杆③ slice 3a — RepaymentDraft tenant-isolation + actor-scope regression net.

The repayment-draft confirm/dismiss/list/replay paths all resolve the draft via
``ledger_scoped_select(RepaymentDraft, tenant_id)`` and the confirm idempotency fingerprint
is actor-scoped (§3.6). The functional tests use the single-owner fixture, so deleting the
ledger scope or the actor scope would still pass them. This file is the missing net:

- a writer of another ledger gets ``repayment_draft_not_found`` (404) on confirm/dismiss of
  ledger A's draft and never sees it in their own inbox (mutation: drop ``ledger_scoped_select``
  → a foreign draft becomes confirmable/dismissable/readable);
- a SECOND writer in the same ledger replaying another actor's confirm Idempotency-Key gets
  ``idempotency_key_reused`` (422), not a HIT (mutation: drop ``actor_account_id`` from the
  confirm fingerprint → the second actor replays past the guard).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Ledger, LedgerMember
from app.services.identity_service import hash_secret, new_session_token


def _seed_personal_ledger(*, name: str, ledger_id: str) -> int:
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id=ledger_id, name=f"{name} 的账本", owner_account_id=account.id))
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="owner"))
        db.commit()
        return account.id


def _seed_member_account(*, name: str, ledger_id: str) -> int:
    with SessionLocal() as db:
        account = Account(display_name=name)
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=ledger_id, account_id=account.id, role="member"))
        db.commit()
        return account.id


def _mint_app_token(*, account_id: int, ledger_id: str) -> str:
    with SessionLocal() as db:
        device = Device(account_id=account_id, device_name="pytest-rd-iso", platform="android")
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=account_id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        db.commit()
        return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_owner_draft(client: TestClient, identity, *, amount_cents: int = 12000) -> dict:
    response = client.post(
        "/api/repayment-drafts",
        headers=identity.app_headers,
        json={"source": "alipay", "amount_cents": amount_cents, "merchant_label": "花呗"},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_owner_debt(client: TestClient, identity, *, principal_amount_cents: int = 50000) -> dict:
    response = client.post(
        "/api/debts",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "花呗",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def test_cross_ledger_draft_is_isolated(client: TestClient, *, identity) -> None:
    # Owner (ledger 'owner') captures a draft; a writer of an unrelated ledger B must not
    # see, confirm, or dismiss it.
    draft = _create_owner_draft(client, identity)
    debt = _create_owner_debt(client, identity)  # so confirm could only fail on the draft scope
    other_account = _seed_personal_ledger(name="ledger-b-owner", ledger_id="ledger_b")
    other_token = _mint_app_token(account_id=other_account, ledger_id="ledger_b")
    other = _headers(other_token)

    # (b) ledger B's inbox never returns ledger A's draft.
    listing = client.get("/api/repayment-drafts", headers=other).json()
    assert all(d["public_id"] != draft["public_id"] for d in listing["items"])

    # (a) ledger B cannot confirm or dismiss ledger A's draft → existence-hidden 404.
    confirm = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers={**other, "Idempotency-Key": str(uuid4())},
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 404, confirm.json()
    assert confirm.json()["error"] == "repayment_draft_not_found"

    dismiss = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=other, json={}
    )
    assert dismiss.status_code == 404, dismiss.json()
    assert dismiss.json()["error"] == "repayment_draft_not_found"

    # The draft is untouched in ledger A.
    a_listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert any(
        d["public_id"] == draft["public_id"] and d["status"] == "pending" for d in a_listing["items"]
    )


def test_confirm_replay_with_different_actor_is_reused_not_hit(client: TestClient, *, identity) -> None:
    # Owner confirms a draft with key K; a SECOND writer in the SAME ledger replaying the
    # SAME key K with the SAME payload differs only by actor → the §3.6 actor-scoped
    # fingerprint rejects it (422 idempotency_key_reused) instead of HITting the owner's result.
    debt = _create_owner_debt(client, identity, principal_amount_cents=50000)
    draft = _create_owner_draft(client, identity, amount_cents=10000)
    key = str(uuid4())
    payload = {"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]}

    first = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json=payload,
    )
    assert first.status_code == 201, first.json()

    second_account = _seed_member_account(name="ledger-owner-writer-2", ledger_id="owner")
    second_token = _mint_app_token(account_id=second_account, ledger_id="owner")
    replay = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers={**_headers(second_token), "Idempotency-Key": key},
        json=payload,
    )
    assert replay.status_code == 422, replay.json()
    assert replay.json()["error"] == "idempotency_key_reused"
