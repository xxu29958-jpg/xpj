"""Shared real-HTTP fixtures for confirmed correction and revision tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import _NativeForm


def idem(headers: dict[str, str], *, key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or str(uuid4())}


def manual_confirmed(
    client: TestClient,
    identity,
    *,
    merchant: str = "初始商家",
    amount_cents: int = 1280,
    tags: str | None = None,
    client_ref: str | None = None,
) -> dict:
    payload = {
        "client_ref": client_ref if client_ref is not None else str(uuid4()),
        "home_currency_code": "CNY",
        "amount_cents": amount_cents,
        "merchant": merchant,
        "category": "餐饮",
        "note": "原始备注",
        "expense_time": "2026-05-04T00:30:00Z",
    }
    if tags is not None:
        payload["tags"] = tags
    response = client.post("/api/expenses/manual", headers=identity.app_headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def revision_history(client: TestClient, identity, expense_id: int, **query: int) -> dict:
    response = client.get(
        f"/api/expenses/{expense_id}/revisions",
        headers=identity.app_headers,
        params=query,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _read_form(response, expense_id):
    return _NativeForm(response.text, f"/web/expenses/{expense_id}/corrections")


def _seed_usd_rate(client: TestClient, identity, rate_date: str, rate: str, *, expected_row_version: int = 0) -> dict:
    response = client.put(
        f"/api/exchange-rates/USD/{rate_date}",
        headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": expected_row_version,
            "home_currency_code": "CNY",
            "currency_code": "USD",
            "rate_date": rate_date,
            "rate_to_cny": rate,
            "source": "manual",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _foreign_expense(client: TestClient, identity, merchant: str) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()),
            "original_currency_code": "USD",
            "original_amount_minor": 10000,
            "expense_time": "2026-05-04T08:00:00Z",
            "merchant": merchant,
            "category": "购物",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_refund(
    client: TestClient,
    identity,
    expense: dict,
    *,
    accounting_date: str = "2026-05-05",
    reason: str = "首次登记",
) -> dict:
    response = client.post(
        f"/api/expenses/{expense['id']}/offsets",
        headers=idem(identity.app_headers),
        json={
            "kind": "refund",
            "original_amount_minor": 2500,
            "accounting_date": accounting_date,
            "reason": reason,
            "expected_row_version": expense["row_version"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
