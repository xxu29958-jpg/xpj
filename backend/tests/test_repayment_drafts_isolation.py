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
  confirm fingerprint → the second actor replays past the guard);
- a SECOND writer in the SAME ledger never sees another member's captures in their inbox and
  gets 404 confirming/dismissing them — repayment captures are personal (§8 / privacy), so
  list/confirm/dismiss are account-scoped, not just ledger-scoped (mutation: drop
  ``created_by_account_id == actor_account_id`` → a co-member's private capture leaks / becomes
  actionable). This is the API-side mirror of the /web audit's account-scope.
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


def test_suggestion_candidate_set_excludes_cross_tenant_debt(client: TestClient, *, identity) -> None:
    # §杠杆③ slice 3b: the suggested-Debt candidate query is tenant-scoped. Owner holds a
    # non-matching external Debt (京东白条); ledger B holds the matching 花呗 Debt. The owner's
    # 花呗 draft must NOT be suggested ledger B's Debt — a dropped tenant filter would leak it.
    owner_debt = client.post(
        "/api/debts",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "京东白条",
            "principal_amount_cents": 50000,
        },
    )
    assert owner_debt.status_code == 201, owner_debt.json()

    other_account = _seed_personal_ledger(name="ledger-b-owner", ledger_id="ledger_b")
    other_token = _mint_app_token(account_id=other_account, ledger_id="ledger_b")
    b_debt = client.post(
        "/api/debts",
        headers={**_headers(other_token), "Idempotency-Key": str(uuid4())},
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "花呗",
            "principal_amount_cents": 50000,
        },
    )
    assert b_debt.status_code == 201, b_debt.json()

    draft = _create_owner_draft(client, identity, amount_cents=20000)  # merchant_label="花呗"
    listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    listed = next(d for d in listing["items"] if d["public_id"] == draft["public_id"])
    # Owner's only candidate is 京东白条 (no 花呗 match) → no suggestion, and never ledger B's Debt.
    assert listed["suggested_debt_public_id"] is None
    assert listed["suggested_debt_public_id"] != b_debt.json()["public_id"]


def test_same_ledger_drafts_are_account_scoped_both_directions(
    client: TestClient, *, identity
) -> None:
    # Two writers in the SAME ledger 'owner'. A repayment capture is one member's phone payment
    # notification (§8 / privacy), so each member's inbox must show ONLY their own — neither
    # sees the other's. (Mutation: drop created_by_account_id from list_repayment_drafts → a
    # co-member's private capture appears in the other's inbox.)
    owner_draft = _create_owner_draft(client, identity, amount_cents=12000)  # created by owner

    member_account = _seed_member_account(name="ledger-owner-writer-2", ledger_id="owner")
    member = _headers(_mint_app_token(account_id=member_account, ledger_id="owner"))
    member_resp = client.post(
        "/api/repayment-drafts",
        headers=member,
        # distinct source/amount → a different dedup key, so this is a separate draft, not a
        # dedup HIT on the owner's.
        json={"source": "wechat", "amount_cents": 34000, "merchant_label": "白条"},
    )
    assert member_resp.status_code == 201, member_resp.json()
    member_draft = member_resp.json()

    owner_ids = {
        d["public_id"]
        for d in client.get("/api/repayment-drafts", headers=identity.app_headers).json()["items"]
    }
    member_ids = {
        d["public_id"] for d in client.get("/api/repayment-drafts", headers=member).json()["items"]
    }

    assert owner_draft["public_id"] in owner_ids
    assert member_draft["public_id"] not in owner_ids  # owner does NOT see the member's capture
    assert member_draft["public_id"] in member_ids
    assert owner_draft["public_id"] not in member_ids  # member does NOT see the owner's capture


def test_same_ledger_other_member_cannot_confirm_my_draft(
    client: TestClient, *, identity
) -> None:
    # A SECOND writer in the same ledger with a FRESH Idempotency-Key (so the reuse-422 above is
    # NOT what fires) still cannot confirm the owner's personal capture → account-scoped 404.
    debt = _create_owner_debt(client, identity)
    draft = _create_owner_draft(client, identity)
    member = _headers(
        _mint_app_token(
            account_id=_seed_member_account(name="ledger-owner-writer-2", ledger_id="owner"),
            ledger_id="owner",
        )
    )
    confirm = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/confirm",
        headers={**member, "Idempotency-Key": str(uuid4())},
        json={"target_debt_public_id": debt["public_id"], "expected_row_version": debt["row_version"]},
    )
    assert confirm.status_code == 404, confirm.json()
    assert confirm.json()["error"] == "repayment_draft_not_found"

    # Untouched: the owner's draft is still pending and confirmable by the owner.
    a_listing = client.get("/api/repayment-drafts", headers=identity.app_headers).json()
    assert any(
        d["public_id"] == draft["public_id"] and d["status"] == "pending" for d in a_listing["items"]
    )


def test_same_ledger_other_member_cannot_dismiss_my_draft(
    client: TestClient, *, identity
) -> None:
    draft = _create_owner_draft(client, identity)
    member = _headers(
        _mint_app_token(
            account_id=_seed_member_account(name="ledger-owner-writer-2", ledger_id="owner"),
            ledger_id="owner",
        )
    )
    dismiss = client.post(
        f"/api/repayment-drafts/{draft['public_id']}/dismiss", headers=member, json={}
    )
    assert dismiss.status_code == 404, dismiss.json()
    assert dismiss.json()["error"] == "repayment_draft_not_found"


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
