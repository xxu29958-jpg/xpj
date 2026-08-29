"""Shared real-HTTP fixtures for confirmed correction and revision tests."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient


def idem(headers: dict[str, str], *, key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or str(uuid4())}


def manual_confirmed(
    client: TestClient,
    identity,
    *,
    merchant: str = "初始商家",
    amount_cents: int = 1280,
    tags: str | None = None,
) -> dict:
    payload = {
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
