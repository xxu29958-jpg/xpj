"""Real HTTP setup shared by the Web debt command consumers."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests._runtime_protocol import negotiated_headers


def _headers(identity) -> dict[str, str]:
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create_debt(
    web_client: TestClient,
    *,
    identity,
    principal_amount_cents: int = 50_000,
) -> dict:
    response = web_client.post(
        "/api/debts",
        headers=negotiated_headers(web_client, _headers(identity)),
        json={
            "home_currency_code": "CNY", "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "测试信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _form(
    debt: dict,
    *,
    idempotency_key: str,
    **values: str,
) -> dict[str, str]:
    return {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "expected_row_version": str(debt["row_version"]),
        "idempotency_key": idempotency_key,
        **values,
    }


def _detail(web_client: TestClient, *, identity, public_id: str) -> dict:
    response = web_client.get(
        f"/api/debts/{public_id}",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()
