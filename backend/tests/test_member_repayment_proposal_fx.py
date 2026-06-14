"""ADR-0049 member repayment proposal FX tests."""

from __future__ import annotations

from datetime import date
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
    _propose_foreign,
    _seed_usd_rate,
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


def test_create_proposal_foreign_amount_idempotent_across_minor_unit_rounding(
    client: TestClient, *, identity
) -> None:
    # §3.6: the create fingerprint hashes the *stored* minor-unit amount, so a
    # lost-response retry whose serializer emits a finer USD decimal (10.004,
    # which rounds HALF_UP to the same 1000 minor units as 10.00) still HITs the
    # same proposal instead of 422 idempotency_key_reused.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=member_id,
        principal_amount_cents=100000,
    )
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    key = str(uuid4())
    headers = {**_member_headers(member_token), "Idempotency-Key": key}
    body = {
        "original_currency_code": "USD",
        "original_amount": "10.00",
        "paid_at": "2026-05-10T04:00:00Z",
    }

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=headers, json=body
    )
    assert first.status_code == 201, first.json()
    assert first.json()["original_amount_minor"] == 1000  # 10.00 USD → 1000 minor units
    proposal_public_id = first.json()["public_id"]

    # Same key, business-identical amount, finer decimal representation that
    # rounds to the same stored minor units → canonical HIT, not key_reused.
    replay = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=headers,
        json={**body, "original_amount": "10.004"},
    )
    assert replay.status_code == 201, replay.json()
    assert replay.json()["public_id"] == proposal_public_id

    proposals = client.get(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=identity.app_headers
    ).json()["items"]
    assert len(proposals) == 1  # the replay HIT, no second proposal created


def test_create_proposal_foreign_paid_at_fingerprint_includes_rate_date(
    client: TestClient, *, identity
) -> None:
    # Same UTC instant can carry different FX date semantics: non-UTC offsets use
    # their local calendar date, while UTC instants are mapped to the accounting
    # timezone. The create fingerprint must not HIT when the freeze date differs.
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(
        client,
        identity.app_headers,
        direction="owed_to_me",
        member_account_id=member_id,
        principal_amount_cents=100000,
    )
    _seed_usd_rate(tenant_id="owner", rate_date=date(2026, 5, 10), rate_to_cny="7.20000000")
    key = str(uuid4())
    headers = {**_member_headers(member_token), "Idempotency-Key": key}
    body = {
        "original_currency_code": "USD",
        "original_amount": "10.00",
        "paid_at": "2026-05-10T00:30:00+14:00",
    }

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals", headers=headers, json=body
    )
    assert first.status_code == 201, first.json()

    replay = client.post(
        f"/api/debts/{debt['public_id']}/repayment-proposals",
        headers=headers,
        json={**body, "paid_at": "2026-05-09T10:30:00Z"},
    )
    assert replay.status_code == 422
    assert replay.json()["error"] == "idempotency_key_reused"

