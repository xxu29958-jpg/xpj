"""ADR-0049 Debt domain slice 2: void facts (§3.4 RepaymentVoid / §3.5 DebtVoid).

Pins the §9 F10 / §11 subset the void writes own: voiding a repayment reopens
the Debt and leaves the original repayment row in place (F10 — append-only, never
deleted); a repayment may be voided at most once (second → 409); a wrong
repayment id is 404; voiding the whole Debt latches ``status='voided'`` and drops
it from open totals while staying GET-visible (audit); a voided Debt rejects
further fact writes; idempotent replay applies once; viewer cannot write (403).

Fold / fact-existence assertions read the rendered API response or a read-only
query of the append-only fact tables, never mutating a DB peek.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Debt, LedgerMember, Repayment

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


def _record_repayment(client: TestClient, identity, public_id: str, amount_cents: int, version: int) -> dict:
    response = client.post(
        f"/api/debts/{public_id}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": amount_cents, "expected_row_version": version},
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _repayment_public_ids(public_id: str) -> list[str]:
    with SessionLocal() as db:
        debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
        assert debt is not None
        return [r.public_id for r in db.scalars(select(Repayment).where(Repayment.debt_id == debt.id))]


def test_void_repayment_reopens_debt_and_keeps_row(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    repaid = _record_repayment(client, identity, debt["public_id"], 10000, debt["row_version"])
    assert repaid["status"] == "cleared"
    repayment_public_id = _repayment_public_ids(debt["public_id"])[0]

    voided = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=_idem(identity.app_headers),
        json={
            "repayment_public_id": repayment_public_id,
            "reason": "记错了",
            "expected_row_version": repaid["row_version"],
        },
    )
    assert voided.status_code == 201, voided.json()
    body = voided.json()
    # Fold reopens: remaining back to 10000, status open again.
    assert body["remaining_amount_cents"] == 10000
    assert body["paid_amount_cents"] == 0
    assert body["status"] == "open"
    assert body["row_version"] == repaid["row_version"] + 1

    # F10: the original repayment row is NOT deleted — it still exists, just
    # excluded from the fold.
    assert _repayment_public_ids(debt["public_id"]) == [repayment_public_id]


def test_void_repayment_twice_is_already_voided(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    repaid = _record_repayment(client, identity, debt["public_id"], 5000, debt["row_version"])
    repayment_public_id = _repayment_public_ids(debt["public_id"])[0]

    first = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=_idem(identity.app_headers),
        json={"repayment_public_id": repayment_public_id, "reason": "a", "expected_row_version": repaid["row_version"]},
    )
    assert first.status_code == 201, first.json()
    second = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=_idem(identity.app_headers),
        json={"repayment_public_id": repayment_public_id, "reason": "b", "expected_row_version": first.json()["row_version"]},
    )
    assert second.status_code == 409, second.json()
    assert second.json()["error"] == "repayment_already_voided"


def test_void_unknown_repayment_is_404(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=_idem(identity.app_headers),
        json={
            "repayment_public_id": "does-not-exist",
            "reason": "x",
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "repayment_not_found"


def test_void_repayment_belonging_to_other_debt_is_404(client: TestClient, *, identity) -> None:
    debt_a = _create_debt(client, identity, principal_amount_cents=10000)
    debt_b = _create_debt(client, identity, principal_amount_cents=10000)
    _record_repayment(client, identity, debt_b["public_id"], 5000, debt_b["row_version"])
    other_repayment_public_id = _repayment_public_ids(debt_b["public_id"])[0]

    # Try to void debt_b's repayment via debt_a's path → not found (it does not
    # belong to debt_a).
    response = client.post(
        f"/api/debts/{debt_a['public_id']}/repayment-voids",
        headers=_idem(identity.app_headers),
        json={
            "repayment_public_id": other_repayment_public_id,
            "reason": "cross",
            "expected_row_version": debt_a["row_version"],
        },
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "repayment_not_found"


def test_void_debt_latches_voided_and_drops_from_open_total(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=30000)
    voided = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "重复记录", "expected_row_version": debt["row_version"]},
    )
    assert voided.status_code == 201, voided.json()
    assert voided.json()["status"] == "voided"
    assert voided.json()["row_version"] == debt["row_version"] + 1

    # Still GET-visible (audit/history).
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["status"] == "voided"

    # Voided Debt no longer contributes to the open total in the list.
    listed = client.get("/api/debts", headers=identity.app_headers)
    open_total = sum(
        item["remaining_amount_cents"]
        for item in listed.json()["items"]
        if item["status"] != "voided"
    )
    assert open_total == 0


def test_void_debt_twice_is_already_voided(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    first = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "a", "expected_row_version": debt["row_version"]},
    )
    assert first.status_code == 201, first.json()
    # A voided Debt is terminal — the §2.1 guard rejects any further fact write.
    second = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "b", "expected_row_version": first.json()["row_version"]},
    )
    assert second.status_code == 409, second.json()
    assert second.json()["error"] == "debt_already_voided"


def test_voided_debt_rejects_further_repayment(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    voided = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "作废", "expected_row_version": debt["row_version"]},
    )
    assert voided.status_code == 201, voided.json()
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "expected_row_version": voided.json()["row_version"]},
    )
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "debt_already_voided"


def test_void_debt_requires_reason(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    response = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "  ", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_reason_required"


def test_void_debt_idempotent_replay_applies_once(client: TestClient, *, identity) -> None:
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    payload = {"reason": "作废", "expected_row_version": debt["row_version"]}

    first = client.post(f"/api/debts/{debt['public_id']}/void", headers=headers, json=payload)
    assert first.status_code == 201, first.json()
    bumped_version = first.json()["row_version"]

    replay = client.post(f"/api/debts/{debt['public_id']}/void", headers=headers, json=payload)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["status"] == "voided"
    # §2.1 replay re-serialises without a second bump.
    assert replay.json()["row_version"] == bumped_version


def test_viewer_cannot_void_debt(client: TestClient, *, identity) -> None:
    # coverage: viewer-write
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    _set_owner_ledger_role("viewer")
    response = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "x", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 403, response.json()
    assert response.json()["error"] == "permission_denied"
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_void_routes_unauthenticated_are_401(client: TestClient, *, identity) -> None:
    # coverage: auth-401 — both void routes reject before business logic.
    debt = _create_debt(client, identity, principal_amount_cents=10000)
    no_auth = {"Idempotency-Key": str(uuid4())}  # no Authorization

    repayment_void = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=no_auth,
        json={"repayment_public_id": "x", "reason": "x", "expected_row_version": debt["row_version"]},
    )
    assert repayment_void.status_code == 401

    debt_void = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=no_auth,
        json={"reason": "x", "expected_row_version": debt["row_version"]},
    )
    assert debt_void.status_code == 401
