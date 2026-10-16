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
from app.models import Debt, DebtVoid, Repayment, RepaymentVoid
from tests.debt_proposal_helpers import _create_external_debt, _record_repayment
from tests.family_ledger_test_support import set_owner_ledger_role

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(app_headers: dict[str, str]) -> dict[str, str]:
    return {**app_headers, "Idempotency-Key": str(uuid4())}


def test_void_repayment_reopens_debt_and_keeps_row(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label="信用卡")
    repaid = _record_repayment(client, identity.app_headers, debt, amount_cents=10000)
    assert repaid["status"] == "cleared"
    repayment_public_id = repaid["repayment_public_id"]
    route = f"/api/debts/{debt['public_id']}/repayment-voids"
    voided = client.post(route, headers=_idem(identity.app_headers), json={
        "repayment_public_id": repayment_public_id, "reason": "记错了",
        "expected_row_version": repaid["row_version"],
    })
    assert voided.status_code == 201, voided.json()
    body = voided.json()
    assert body["remaining_amount_cents"] == 10000
    assert body["paid_amount_cents"] == 0
    assert body["status"] == "open"
    assert body["row_version"] == repaid["row_version"] + 1

    second = client.post(route, headers=_idem(identity.app_headers), json={
        "repayment_public_id": repayment_public_id, "reason": "再作废",
        "expected_row_version": body["row_version"],
    })
    assert second.status_code == 409, second.json()
    assert second.json()["error"] == "repayment_already_voided"
    with SessionLocal() as db:
        saved = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        repayments = list(db.scalars(select(Repayment).where(Repayment.debt_id == saved.id)))
        assert [row.public_id for row in repayments] == [repayment_public_id]
        assert db.scalars(select(RepaymentVoid.reason).where(RepaymentVoid.repayment_id == repayments[0].id)).all() == ["记错了"]
        assert saved.row_version == body["row_version"]


def test_void_unknown_repayment_is_404(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label='信用卡')
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
    debt_a = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label='信用卡')
    debt_b = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label='信用卡')
    repaid_b = _record_repayment(client, identity.app_headers, debt_b, amount_cents=5000)
    other_repayment_public_id = repaid_b["repayment_public_id"]

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
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=30000, counterparty_label="信用卡")
    route = f"/api/debts/{debt['public_id']}/void"
    headers = _idem(identity.app_headers)
    payload = {"reason": "重复记录", "expected_row_version": debt["row_version"]}
    voided = client.post(route, headers=headers, json=payload)
    assert voided.status_code == 201, voided.json()
    body = voided.json()
    assert body["status"] == "voided"
    assert body["row_version"] == debt["row_version"] + 1

    replay = client.post(route, headers=headers, json=payload)
    assert replay.status_code == 201, replay.json()
    assert replay.json() == body
    second = client.post(route, headers=_idem(identity.app_headers), json={
        "reason": "再作废", "expected_row_version": body["row_version"],
    })
    assert second.status_code == 409, second.json()
    assert second.json()["error"] == "debt_already_voided"
    repayment = client.post(f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(identity.app_headers),
        json={"amount_cents": 1000, "expected_row_version": body["row_version"]})
    assert repayment.status_code == 409, repayment.json()
    assert repayment.json()["error"] == "debt_already_voided"

    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    assert detail.json()["status"] == "voided"
    assert detail.json()["row_version"] == body["row_version"]
    listed = client.get("/api/debts", headers=identity.app_headers)
    assert listed.status_code == 200, listed.json()
    assert sum(item["remaining_amount_cents"] for item in listed.json()["items"] if item["status"] != "voided") == 0
    with SessionLocal() as db:
        saved = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        assert db.scalars(select(DebtVoid.reason).where(DebtVoid.debt_id == saved.id)).all() == ["重复记录"]
        assert db.scalars(select(Repayment.id).where(Repayment.debt_id == saved.id)).all() == []


def test_void_debt_requires_reason(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label='信用卡')
    response = client.post(
        f"/api/debts/{debt['public_id']}/void",
        headers=_idem(identity.app_headers),
        json={"reason": "  ", "expected_row_version": debt["row_version"]},
    )
    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "debt_reason_required"


def test_viewer_cannot_void_debt(client: TestClient, *, identity) -> None:
    # coverage: viewer-write
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label='信用卡')
    set_owner_ledger_role("viewer")
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
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000, counterparty_label='信用卡')
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
