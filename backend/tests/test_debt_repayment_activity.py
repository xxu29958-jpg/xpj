"""Restart-safe repayment fact history and its authorization boundaries."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import Account, AuthToken, Debt, Device, Ledger, LedgerMember
from app.services.debt_service import list_repayment_facts
from app.services.identity_service import hash_secret, new_session_token


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _owner_account_id() -> int:
    with SessionLocal() as db:
        account_id = db.scalar(
            select(LedgerMember.account_id)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert account_id is not None
        return account_id


def _create_external_debt(
    client: TestClient,
    headers: dict[str, str],
    *,
    principal_amount_cents: int = 10_000,
) -> dict:
    response = client.post(
        "/api/debts",
        headers=_idem(headers),
        json={
            "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "测试借款",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _record_repayment(
    client: TestClient,
    headers: dict[str, str],
    debt: dict,
    *,
    amount_cents: int,
) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=_idem(headers),
        json={
            "amount_cents": amount_cents,
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _void_repayment(
    client: TestClient,
    headers: dict[str, str],
    debt: dict,
    *,
    repayment_public_id: str,
    reason: str,
) -> dict:
    response = client.post(
        f"/api/debts/{debt['public_id']}/repayment-voids",
        headers=_idem(headers),
        json={
            "repayment_public_id": repayment_public_id,
            "reason": reason,
            "expected_row_version": debt["row_version"],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _set_owner_role(role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


def _seed_cross_ledger_member_debt() -> tuple[str, str]:
    """Return ``(debt_public_id, debtor_token)`` for owner-as-creditor."""
    creditor_id = _owner_account_id()
    with SessionLocal() as db:
        debtor = Account(display_name="跨账本债务人")
        db.add(debtor)
        db.flush()
        ledger_id = f"debtor-{uuid4()}"
        db.add(
            Ledger(
                ledger_id=ledger_id,
                name="债务人的私人账本",
                owner_account_id=debtor.id,
            )
        )
        db.add(
            LedgerMember(
                ledger_id=ledger_id,
                account_id=debtor.id,
                role="owner",
            )
        )
        device = Device(
            account_id=debtor.id,
            device_name="pytest-cross-ledger-debtor",
            platform="android",
        )
        db.add(device)
        db.flush()
        token = new_session_token()
        db.add(
            AuthToken(
                token_hash=hash_secret(token),
                account_id=debtor.id,
                device_id=device.id,
                ledger_id=ledger_id,
                scope="app",
            )
        )
        debt = Debt(
            tenant_id=ledger_id,
            owner_account_id=debtor.id,
            created_by_account_id=debtor.id,
            direction="i_owe",
            counterparty_type="member",
            counterparty_account_id=creditor_id,
            principal_amount_cents=4_000,
            home_currency_code="CNY",
            status="open",
            source_type="bill_split",
            source_id=str(uuid4()),
        )
        db.add(debt)
        db.commit()
        return debt.public_id, token


def test_route_restores_repayment_history_and_void_fact(
    client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(client, identity.app_headers)
    first = _record_repayment(
        client,
        identity.app_headers,
        debt,
        amount_cents=3_000,
    )
    second = _record_repayment(
        client,
        identity.app_headers,
        first,
        amount_cents=2_000,
    )
    _void_repayment(
        client,
        identity.app_headers,
        second,
        repayment_public_id=first["repayment_public_id"],
        reason="重复记了一次",
    )

    response = client.get(
        f"/api/debts/{debt['public_id']}/repayments?page=1&page_size=100",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["debt_public_id"] == debt["public_id"]
    assert body["home_currency_code"] == "CNY"
    assert body["page"] == 1
    assert body["page_size"] == 100
    assert body["total"] == 2

    by_id = {item["public_id"]: item for item in body["items"]}
    active = by_id[second["repayment_public_id"]]
    assert active["amount_cents"] == 2_000
    assert active["status"] == "active"
    assert active["void_fact"] is None

    voided = by_id[first["repayment_public_id"]]
    assert voided["amount_cents"] == 3_000
    assert voided["status"] == "voided"
    assert voided["void_fact"]["reason"] == "重复记了一次"
    assert voided["void_fact"]["public_id"]
    assert voided["created_at"].endswith("Z")
    assert voided["void_fact"]["created_at"].endswith("Z")
    assert "actor_account_id" not in voided
    assert "idempotency_key" not in voided
    assert "actor_account_id" not in voided["void_fact"]
    assert "idempotency_key" not in voided["void_fact"]

    # The same facts drive the canonical fold: only the active ¥20 repayment remains.
    detail = client.get(
        f"/api/debts/{debt['public_id']}",
        headers=identity.app_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["paid_amount_cents"] == 2_000
    assert detail.json()["remaining_amount_cents"] == 8_000


def test_service_paginates_newest_first_with_stable_fact_ids(
    client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(
        client,
        identity.app_headers,
        principal_amount_cents=20_000,
    )
    first = _record_repayment(client, identity.app_headers, debt, amount_cents=1_000)
    second = _record_repayment(client, identity.app_headers, first, amount_cents=2_000)
    third = _record_repayment(client, identity.app_headers, second, amount_cents=3_000)

    with SessionLocal() as db:
        page_one = list_repayment_facts(
            db,
            tenant_id="owner",
            actor_account_id=_owner_account_id(),
            public_id=debt["public_id"],
            page=1,
            page_size=2,
        )
        page_two = list_repayment_facts(
            db,
            tenant_id="owner",
            actor_account_id=_owner_account_id(),
            public_id=debt["public_id"],
            page=2,
            page_size=2,
        )

    assert page_one.total == 3
    assert [item.public_id for item in page_one.items] == [
        third["repayment_public_id"],
        second["repayment_public_id"],
    ]
    assert [item.public_id for item in page_two.items] == [
        first["repayment_public_id"],
    ]


def test_viewer_can_read_repayment_facts(
    client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(client, identity.app_headers)
    _record_repayment(client, identity.app_headers, debt, amount_cents=1_000)
    _set_owner_role("viewer")

    response = client.get(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.json()
    assert response.json()["total"] == 1


def test_external_debt_activity_is_ledger_scoped_and_existence_hidden(
    client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(client, identity.app_headers)
    _record_repayment(client, identity.app_headers, debt, amount_cents=1_000)

    route_response = client.get(
        f"/api/debts/{debt['public_id']}/repayments",
        headers=identity.gray_app_headers,
    )
    assert route_response.status_code == 404
    assert route_response.json()["error"] == "debt_not_found"

    with SessionLocal() as db, pytest.raises(AppError) as error:
        list_repayment_facts(
            db,
            tenant_id="tester_1",
            actor_account_id=_owner_account_id(),
            public_id=debt["public_id"],
            page=1,
            page_size=50,
        )
    assert error.value.error == "debt_not_found"
    assert error.value.status_code == 404


def test_member_counterparty_reads_cross_ledger_committed_repayment(
    client: TestClient,
    *,
    identity,
) -> None:
    debt_public_id, debtor_token = _seed_cross_ledger_member_debt()
    debtor_headers = {"Authorization": f"Bearer {debtor_token}"}

    proposal = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals",
        headers=_idem(debtor_headers),
        json={"proposed_amount_cents": 1_500},
    )
    assert proposal.status_code == 201, proposal.json()
    confirmed = client.post(
        f"/api/debts/{debt_public_id}/repayment-proposals/"
        f"{proposal.json()['public_id']}/confirm",
        headers=_idem(identity.app_headers),
        json={"expected_row_version": 1},
    )
    assert confirmed.status_code == 201, confirmed.json()
    assert confirmed.json()["ledger_id"] is None

    response = client.get(
        f"/api/debts/{debt_public_id}/repayments",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.json()
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["amount_cents"] == 1_500
    assert response.json()["items"][0]["status"] == "active"
    assert "ledger_id" not in response.json()


def test_repayment_activity_requires_auth_and_bounds_page_size(
    client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(client, identity.app_headers)

    unauthenticated = client.get(
        f"/api/debts/{debt['public_id']}/repayments",
    )
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"] == "invalid_token"

    oversized = client.get(
        f"/api/debts/{debt['public_id']}/repayments?page_size=101",
        headers=identity.app_headers,
    )
    assert oversized.status_code == 422
    assert oversized.json()["error"] == "invalid_request"


def test_openapi_exposes_repayment_fact_read_model() -> None:
    app.openapi_schema = None
    spec = app.openapi()
    operation = spec["paths"]["/api/debts/{public_id}/repayments"]["get"]
    response_schema = operation["responses"]["200"]["content"][
        "application/json; charset=utf-8"
    ]["schema"]
    assert response_schema == {
        "$ref": "#/components/schemas/RepaymentFactListResponse"
    }
    status_schema = spec["components"]["schemas"]["RepaymentFactResponse"][
        "properties"
    ]["status"]
    assert status_schema["enum"] == ["active", "voided"]
