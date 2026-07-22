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

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Account, AuthToken, Device, Ledger, LedgerMember, RepaymentDraft
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


# --- issue #224 (C3): the dedup idempotency domain is (tenant, account, key) ------

# Byte-identical capture payload (fixed captured_at pins the 30-min window bucket), so
# both posters derive the SAME draft_idempotency_key.
_SHARED_CAPTURE = {
    "source": "alipay",
    "amount_cents": 12345,
    "merchant_label": "花呗",
    "notification_key": "shared-post-1",
    "captured_at": "2026-07-01T08:00:00Z",
}


def _member_headers(*, name: str) -> dict[str, str]:
    return _headers(
        _mint_app_token(
            account_id=_seed_member_account(name=name, ledger_id="owner"),
            ledger_id="owner",
        )
    )


def _inbox_ids(client: TestClient, headers: dict[str, str], *, status: str = "pending") -> set[str]:
    listing = client.get(f"/api/repayment-drafts?status={status}", headers=headers).json()
    return {d["public_id"] for d in listing["items"]}


def test_same_key_cross_account_creates_distinct_drafts_no_leak(client: TestClient, *, identity) -> None:
    # Two members of the SAME ledger post the byte-identical notification (same dedup key).
    # Each must get their OWN pending draft — before the fix the tenant-wide unique constraint
    # plus the account-less first-check returned the FIRST poster's draft to the second poster
    # (cross-account leak of the draft + its public_id).
    owner_resp = client.post("/api/repayment-drafts", headers=identity.app_headers, json=_SHARED_CAPTURE)
    assert owner_resp.status_code == 201, owner_resp.json()
    owner_draft = owner_resp.json()

    member = _member_headers(name="ledger-owner-writer-2")
    member_resp = client.post("/api/repayment-drafts", headers=member, json=_SHARED_CAPTURE)
    assert member_resp.status_code == 201, member_resp.json()
    member_draft = member_resp.json()

    assert member_draft["public_id"] != owner_draft["public_id"]
    # Neither capture leaks into the other's inbox.
    assert _inbox_ids(client, identity.app_headers) == {owner_draft["public_id"]}
    assert _inbox_ids(client, member) == {member_draft["public_id"]}


def test_same_account_same_key_replay_hits_own_draft(client: TestClient, *, identity) -> None:
    # Response-loss replay: the SAME account re-posting the identical notification gets its OWN
    # existing draft back (HIT, never a twin) — and the HIT stays account-scoped even while a
    # co-member holds a same-key draft (the lookup can never wander into the co-member's row).
    first = client.post("/api/repayment-drafts", headers=identity.app_headers, json=_SHARED_CAPTURE)
    assert first.status_code == 201, first.json()
    member = _member_headers(name="ledger-owner-writer-2")
    member_first = client.post("/api/repayment-drafts", headers=member, json=_SHARED_CAPTURE)
    assert member_first.status_code == 201, member_first.json()

    replay = client.post("/api/repayment-drafts", headers=identity.app_headers, json=_SHARED_CAPTURE)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == first.json()["public_id"]

    member_replay = client.post("/api/repayment-drafts", headers=member, json=_SHARED_CAPTURE)
    assert member_replay.status_code == 201, member_replay.json()
    assert member_replay.json()["public_id"] == member_first.json()["public_id"]

    # Still exactly one pending draft per account — the replays inserted no twins.
    assert _inbox_ids(client, identity.app_headers) == {first.json()["public_id"]}
    assert _inbox_ids(client, member) == {member_first.json()["public_id"]}


def test_repost_after_dismiss_returns_terminal_draft_not_resurrected(client: TestClient, *, identity) -> None:
    # Terminal-state guard on the create path: re-posting the same notification after the draft
    # was dismissed HITs the TERMINAL row (returns it unchanged) instead of resurrecting a fresh
    # pending twin — a resolved capture can never come back as actionable.
    created = client.post("/api/repayment-drafts", headers=identity.app_headers, json=_SHARED_CAPTURE)
    assert created.status_code == 201, created.json()
    dismiss = client.post(
        f"/api/repayment-drafts/{created.json()['public_id']}/dismiss",
        headers=identity.app_headers,
        json={},
    )
    assert dismiss.status_code == 201, dismiss.json()

    repost = client.post("/api/repayment-drafts", headers=identity.app_headers, json=_SHARED_CAPTURE)
    assert repost.status_code == 201, repost.json()
    assert repost.json()["public_id"] == created.json()["public_id"]
    assert repost.json()["status"] == "dismissed"
    assert created.json()["public_id"] not in _inbox_ids(client, identity.app_headers)


def test_db_unique_constraint_is_account_scoped(client: TestClient, *, identity) -> None:
    # Pin the DB backstop directly: (tenant_id, draft_idempotency_key) may repeat ACROSS
    # accounts, but never twice for the SAME account. Before the fix the second insert here
    # (different account, same tenant+key) violated the tenant-wide constraint.
    captured = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    key = "ab" * 32

    def _draft(account_id: int) -> RepaymentDraft:
        return RepaymentDraft(
            tenant_id="owner",
            created_by_account_id=account_id,
            source="alipay",
            amount_cents=12345,
            home_currency_code="CNY",
            merchant_label="花呗",
            captured_at=captured,
            draft_idempotency_key=key,
            status="pending",
            created_at=captured,
        )

    with SessionLocal() as db:
        owner_id = db.scalar(select(Account.id).order_by(Account.id.asc()).limit(1))
        assert owner_id is not None
        other = Account(display_name="rd-idem-scope")
        db.add(other)
        db.flush()

        db.add(_draft(owner_id))
        db.add(_draft(other.id))  # same tenant+key, DIFFERENT account → allowed
        db.flush()

        db.add(_draft(owner_id))  # same tenant+account+key → the backstop fires
        with pytest.raises(IntegrityError), db.begin_nested():
            db.flush()
