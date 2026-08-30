"""Stable recurring merchant validation errors at the public API boundary."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_candidate_confirmation_rejects_display_merchant_overflow_with_domain_error(
    client: TestClient,
    *,
    identity,
) -> None:
    response = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json={
            "merchant": "x" * 256,
            "amount_cents": 20000,
            "occurrence_count": 3,
            "last_seen_at": "2026-05-05T12:00:00Z",
            "confidence": "high",
            "frequency": "monthly",
        },
    )

    assert response.status_code == 422, response.json()
    assert response.json()["error"] == "recurring_merchant_too_long"
