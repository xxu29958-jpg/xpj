from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "path",
    [
        "/api/stats/monthly?month=2026-13",
        "/api/stats/monthly?month=0000-05",
        "/api/stats/lifestyle?month=2026-5",
        "/api/expenses/confirmed?month=2026-13",
        "/api/expenses/export.csv?month=0000-05",
    ],
)
def test_month_filters_reject_invalid_month_labels(client: TestClient, path: str, *, identity) -> None:
    response = client.get(path, headers=identity.app_headers)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
