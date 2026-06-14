"""ADR-0049 Debt domain slice 2: signed adjustment facts (§3.3).

Pins the §9 F9 / §11 subset the adjustment write owns: a positive adjustment
raises ``remaining``; a negative adjustment lowers it but never below 0
(over-reduction → ``debt_adjustment_negative_remaining`` 422); ``reason`` is
required; an adjustment appends a fact and leaves the frozen principal column
unchanged (F9 — the fold moves, the principal does not); an idempotent replay
applies once; viewer cannot write (403); a stale ``expected_row_version`` is 409.

Fold assertions read the rendered API response, never a DB peek (mirroring slice 1).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Debt, LedgerMember
from app.services.time_service import now_utc

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


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
            "counterparty_label": "信用卡",
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


def test_positive_adjustment_raises_remaining(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 5000, "reason": "滞纳金", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["remaining_amount_cents"] == 55000  # 50000 + 5000
    # F9: the frozen principal column is unchanged; only the fold moved.
    assert body["principal_amount_cents"] == 50000
    assert body["row_version"] == debt["row_version"] + 1


def test_negative_adjustment_lowers_remaining(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": -8000, "reason": "减免", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["remaining_amount_cents"] == 42000  # 50000 - 8000
    assert body["principal_amount_cents"] == 50000


def test_adjustment_cannot_drive_remaining_negative(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": -10001, "reason": "过度减免", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_adjustment_negative_remaining"
    # Rejected → no fold change, no bump.
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.json()["remaining_amount_cents"] == 10000
    assert detail.json()["row_version"] == debt["row_version"]


def test_adjustment_to_exact_zero_clears(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": -10000, "reason": "全额减免", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["remaining_amount_cents"] == 0
    assert body["status"] == "cleared"


def test_adjustment_requires_reason(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "reason": "   ", "expected_row_version": debt["row_version"]},
    )
    # Whitespace-only reason is rejected by the service after strip.
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_reason_required"


def test_adjustment_idempotent_replay_applies_once(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    payload = {"amount_cents": 3000, "reason": "手续费", "expected_row_version": debt["row_version"]}

    first = client.post(f"/api/debts/{debt['public_id']}/adjustments", headers=headers, json=payload)
    assert first.status_code == 201, first.json()
    assert first.json()["remaining_amount_cents"] == 53000
    bumped_version = first.json()["row_version"]

    replay = client.post(f"/api/debts/{debt['public_id']}/adjustments", headers=headers, json=payload)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["remaining_amount_cents"] == 53000
    assert replay.json()["row_version"] == bumped_version


def test_manual_member_adjustment_requires_confirmation_flow(
    client: TestClient, *, identity
) -> None:
    debt = _seed_manual_member_debt(principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={
            "amount_cents": 1000,
            "reason": "member-confirmation-required",
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


def test_viewer_cannot_record_adjustment(client: TestClient, *, identity) -> None:
    # coverage: viewer-write
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    _set_owner_ledger_role("viewer")
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "reason": "x", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "permission_denied"
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_adjustment_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    # coverage: auth-401 — no Authorization, auth runs before business logic.
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers={"Idempotency-Key": str(uuid4())},  # no Authorization
        json={"amount_cents": 1000, "reason": "x", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 401


def test_adjustment_stale_expected_row_version_is_conflict(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=50000)
    first = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "reason": "a", "expected_row_version": debt["row_version"]},
    )
    assert first.status_code == 201, first.json()
    stale = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "reason": "b", "expected_row_version": debt["row_version"]},
    )
    assert stale.status_code == 409, stale.json()
    assert stale.json()["error"] == "state_conflict"
