"""ADR-0049 §7.0 / 8e-6e — POST /api/debts/{public_id}/kind (correct a Debt's classification).

The create path accepts ``debt_kind`` up front (test_debts); this OCC setter is the post-hoc
correction entry (Android detail-screen type chip / fix a bill_split or NLS-created Debt). Pins
the cross-cutting guards: writer-only (viewer 403 / no-auth 401), idempotency-key required +
replay-safe, OCC stale-intent (409), unknown Debt (404), and the DebtKind Literal (invalid → 422).
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember

VIEWER_WRITE_MESSAGE = "当前角色为只读，无法修改账本。"


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _set_owner_ledger_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _create_external_debt(client: TestClient, identity, *, debt_kind: str | None = None) -> dict:
    body: dict = {
        "direction": "i_owe",
        "counterparty_type": "external",
        "counterparty_label": "招商信用卡",
        "principal_amount_cents": 50000,
    }
    if debt_kind is not None:
        body["debt_kind"] = debt_kind
    response = client.post("/api/debts", headers=_idem(identity.app_headers), json=body)
    assert response.status_code == 201, response.json()
    return response.json()


def _set_kind(client: TestClient, identity, public_id: str, *, debt_kind: str, expected_row_version: int, headers=None):
    return client.post(
        f"/api/debts/{public_id}/kind",
        headers=headers if headers is not None else _idem(identity.app_headers),
        json={"debt_kind": debt_kind, "expected_row_version": expected_row_version},
    )


def test_set_debt_kind_updates_and_bumps_row_version(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)  # defaults to unspecified, row_version 1
    assert debt["debt_kind"] == "unspecified"
    response = _set_kind(client, identity, debt["public_id"], debt_kind="one_off", expected_row_version=1)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["debt_kind"] == "one_off"
    assert body["row_version"] == 2  # OCC token bumped


def test_set_debt_kind_stale_row_version_is_409(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)
    response = _set_kind(client, identity, debt["public_id"], debt_kind="revolving", expected_row_version=99)
    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "state_conflict"


def test_set_debt_kind_viewer_is_403(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)
    _set_owner_ledger_role("viewer")
    response = _set_kind(client, identity, debt["public_id"], debt_kind="installment", expected_row_version=1)
    assert response.status_code == 403, response.json()
    assert response.json()["message"] == VIEWER_WRITE_MESSAGE


def test_set_debt_kind_unauthenticated_is_401(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)
    response = client.post(
        f"/api/debts/{debt['public_id']}/kind",
        headers={"Idempotency-Key": str(uuid4())},  # NO Authorization header
        json={"debt_kind": "one_off", "expected_row_version": 1},
    )
    assert response.status_code == 401


def test_set_debt_kind_requires_idempotency_key(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)
    response = client.post(
        f"/api/debts/{debt['public_id']}/kind",
        headers=identity.app_headers,  # no Idempotency-Key
        json={"debt_kind": "one_off", "expected_row_version": 1},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_key_required"


def test_set_debt_kind_idempotent_replay(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    first = _set_kind(client, identity, debt["public_id"], debt_kind="revolving", expected_row_version=1, headers=headers)
    assert first.status_code == 200, first.json()
    assert first.json()["row_version"] == 2
    # Same key + same body → replay re-serialises WITHOUT a second bump (row_version stays 2).
    replay = _set_kind(client, identity, debt["public_id"], debt_kind="revolving", expected_row_version=1, headers=headers)
    assert replay.status_code == 200, replay.json()
    assert replay.json()["debt_kind"] == "revolving"
    assert replay.json()["row_version"] == 2


def test_set_debt_kind_rejects_invalid_kind(client: TestClient, *, identity) -> None:
    debt = _create_external_debt(client, identity)
    response = _set_kind(client, identity, debt["public_id"], debt_kind="credit_card", expected_row_version=1)
    assert response.status_code == 422, response.json()


def test_set_debt_kind_unknown_debt_is_404(client: TestClient, *, identity) -> None:
    response = _set_kind(client, identity, "does-not-exist", debt_kind="one_off", expected_row_version=1)
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "debt_not_found"


def test_set_debt_kind_cross_tenant_is_404(client: TestClient, *, identity) -> None:
    # Ledger-scoped: a writer in a DIFFERENT ledger cannot reclassify this Debt — get_debt +
    # claim_row_with_token both filter by tenant, so it is the same existence-hiding 404 as a
    # missing id (no cross-tenant write). Defensive isolation pin (adversarial-review P3).
    debt = _create_external_debt(client, identity)  # owner ledger
    response = client.post(
        f"/api/debts/{debt['public_id']}/kind",
        headers={**identity.gray_app_headers, "Idempotency-Key": str(uuid4())},
        json={"debt_kind": "one_off", "expected_row_version": 1},
    )
    assert response.status_code == 404, response.json()
    assert response.json()["error"] == "debt_not_found"
