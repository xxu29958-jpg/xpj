"""Restart-safe repayment fact history and its authorization boundaries."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.services.debt_service import list_repayment_facts
from tests._runtime_protocol import current_protocol_headers
from tests.debt_proposal_helpers import (
    _create_external_debt,
    _idem,
    _owner_account_id,
    _record_repayment,
    _seed_cross_ledger_member_debt,
    _void_repayment,
)
from tests.debt_proposal_helpers import _set_owner_ledger_role as _set_owner_role


def test_route_restores_repayment_history_and_void_fact(
    client: TestClient,
    *,
    identity,
) -> None:
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10_000)
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
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10_000)
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
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10_000)
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
    debtor_headers = current_protocol_headers({"Authorization": f"Bearer {debtor_token}"})

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
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10_000)

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
