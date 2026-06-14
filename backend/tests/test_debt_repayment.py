"""ADR-0049 Debt domain slice 2: committed repayment facts (§3.1).

Pins the §9 F6/F7/F8(single-writer) / §11 subset the repayment write owns:
creditor records a repayment and ``remaining`` drops once (F6); an idempotent
replay returns the same canonical fold without applying twice (F7); a repayment
over remaining is rejected (F8 single-thread); distinct keys are not deduped;
same key + different fingerprint is a reuse; a foreign-currency repayment freezes
its home ``amount_cents`` from the [[0027]] snapshot for ``paid_at`` (pending →
409); viewer cannot write (§5/§11 → 403); a stale ``expected_row_version`` is a
409; ``amount <= 0`` is 422; a missing Idempotency-Key is 422.

Idempotency / fold assertions read the rendered API response (``remaining_amount_cents``
+ Debt ``row_version``), never a DB peek — mirroring slice 1.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, ExchangeRate, LedgerMember
from app.services.time_service import now_utc

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def _seed_usd_rate(*, tenant_id: str, rate_date: date, rate_to_cny: str) -> None:
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


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _create_debt(client: TestClient, identity, *, principal_amount_cents: int = 50000) -> dict:
    response = client.post(
        "/api/debts",
        headers=_idem(identity.app_headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "招商信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _seed_manual_member_debt(*, principal_amount_cents: int = 10000) -> dict:
    with SessionLocal() as db:
        owner = db.scalar(select(Account).order_by(Account.id.asc()).limit(1))
        assert owner is not None
        counterparty = Account(display_name="member-counterparty")
        db.add(counterparty)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id="owner",
                account_id=counterparty.id,
                role="member",
            )
        )
        now = now_utc()
        debt = Debt(
            tenant_id="owner",
            owner_account_id=owner.id,
            created_by_account_id=owner.id,
            direction="owed_to_me",
            counterparty_type="member",
            counterparty_account_id=counterparty.id,
            principal_amount_cents=principal_amount_cents,
            home_currency_code="CNY",
            status="open",
            source_type="manual",
            created_at=now,
            updated_at=now,
        )
        db.add(debt)
        db.commit()
        return {"public_id": debt.public_id, "row_version": debt.row_version}


def test_record_repayment_reduces_remaining_once(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 20000, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["remaining_amount_cents"] == 30000  # 50000 - 20000
    assert body["paid_amount_cents"] == 20000
    assert body["status"] == "open"
    assert body["repayment_public_id"]
    # The parent Debt row_version bumped once (§2.1).
    assert body["row_version"] == debt["row_version"] + 1


def test_repayment_clearing_remaining_latches_cleared(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 10000, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["remaining_amount_cents"] == 0
    assert body["paid_amount_cents"] == 10000
    assert body["status"] == "cleared"


def test_repayment_idempotent_replay_applies_once(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    payload = {"amount_cents": 15000, "expected_row_version": debt["row_version"]}

    first = client.post(f"/api/debts/{debt['public_id']}/repayments", headers=headers, json=payload)
    assert first.status_code == 201, first.json()
    assert first.json()["remaining_amount_cents"] == 35000
    bumped_version = first.json()["row_version"]

    # Same key + same fingerprint → canonical fold, applied once. The parent row
    # is NOT bumped a second time (§2.1 replay does not bump).
    replay = client.post(f"/api/debts/{debt['public_id']}/repayments", headers=headers, json=payload)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["remaining_amount_cents"] == 35000
    assert replay.json()["row_version"] == bumped_version
    assert replay.json()["repayment_public_id"] == first.json()["repayment_public_id"]

    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 35000


def test_repayment_distinct_keys_are_not_deduped(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    version = debt["row_version"]
    first = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 10000, "expected_row_version": version},
    )
    assert first.status_code == 201, first.json()
    next_version = first.json()["row_version"]
    # A genuinely distinct repayment (its own key) applies on top.
    second = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 10000, "expected_row_version": next_version},
    )
    assert second.status_code == 201, second.json()
    assert second.json()["remaining_amount_cents"] == 30000  # 50000 - 10000 - 10000


def test_manual_member_repayment_requires_confirmation_flow(
    client: TestClient, *, identity
) -> None:
    debt = _seed_manual_member_debt(principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


def test_repayment_same_key_different_fingerprint_is_reused(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    version = debt["row_version"]
    first = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=headers,
        json={"amount_cents": 10000, "expected_row_version": version},
    )
    assert first.status_code == 201, first.json()
    mismatch = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=headers,
        json={"amount_cents": 99999, "expected_row_version": version},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"] == "idempotency_key_reused"


def test_repayment_over_remaining_is_rejected(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 10001, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_overpay_rejected"
    # Rejected → no fold change, no bump.
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 10000
    assert detail.json()["row_version"] == debt["row_version"]


def test_repayment_over_remaining_after_partial_is_rejected(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    first = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 6000, "expected_row_version": debt["row_version"]},
    )
    assert first.status_code == 201, first.json()
    assert first.json()["remaining_amount_cents"] == 4000
    # remaining is now 4000; a 5000 repayment must be rejected from authoritative
    # facts (F8 single-thread analogue).
    second = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 5000, "expected_row_version": first.json()["row_version"]},
    )
    assert second.status_code == 422, second.json()
    assert second.json()["error"] == "debt_overpay_rejected"


def test_repayment_non_positive_amount_is_422(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 0, "expected_row_version": debt["row_version"]},
    )
    # Pydantic ``gt=0`` rejects at validation.
    assert response.status_code == 422, response.json()


def test_repayment_missing_idempotency_key_is_422(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=identity.app_headers,  # no Idempotency-Key
        json={"amount_cents": 1000, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_required"


def test_repayment_stale_expected_row_version_is_conflict(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    # First repayment bumps row_version to debt+1.
    first = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 5000, "expected_row_version": debt["row_version"]},
    )
    assert first.status_code == 201, first.json()
    # A second repayment that still carries the ORIGINAL (now stale) version is a
    # state_conflict (§2.1 stale-intent fence) — caught before the overpay check.
    stale = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 5000, "expected_row_version": debt["row_version"]},
    )
    assert stale.status_code == 409, stale.json()
    assert stale.json()["error"] == "state_conflict"


def test_repayment_on_missing_debt_is_404(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/debts/does-not-exist/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "expected_row_version": 1},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "debt_not_found"


def test_repayment_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    # coverage: auth-401 — no Authorization, auth runs before business logic.
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={"amount_cents": 1000, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 401


def test_viewer_cannot_record_repayment(client: TestClient, *, identity) -> None:
    # coverage: viewer-write
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    _set_owner_ledger_role("viewer")
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "permission_denied"
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_foreign_currency_repayment_freezes_home_cents(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=100000)
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={
            "original_currency": "USD",
            "original_amount": "100.00",
            "paid_at": "2026-05-10T04:00:00Z",
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    # 100 USD * 7.2 = 720.00 CNY → 72000 home cents repaid.
    assert body["paid_amount_cents"] == 72000
    assert body["remaining_amount_cents"] == 28000  # 100000 - 72000


def test_foreign_currency_repayment_pending_rate_is_rejected(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=100000)
    # No USD rate seeded for that paid_at date → cannot freeze → 409.
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={
            "original_currency": "USD",
            "original_amount": "50.00",
            "paid_at": "2026-05-10T04:00:00Z",
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "exchange_rate_pending"
