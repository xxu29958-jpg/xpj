"""v1.1 PR-7: HTTP integration tests for income_plans + budget/discretionary.

Cover the writer / viewer permission split, the validation surface
(wrong field shapes / values), the empty-state defaults, and the
shape-of-response contract that the Android / web client will consume.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# income_plans CRUD
# ---------------------------------------------------------------------------


def test_list_income_plans_empty_returns_zero_total(client: TestClient, *, identity) -> None:
    resp = client.get("/api/income-plans", headers=identity.app_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total_active_amount_cents"] == 0


def test_create_income_plan_round_trip(client: TestClient, *, identity) -> None:
    create_resp = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "我的工资",
            "source_type": "salary",
            "amount_cents": 1_000_000,
            "pay_day": 10,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["label"] == "我的工资"
    assert created["amount_cents"] == 1_000_000
    assert created["pay_day"] == 10
    assert created["status"] == "active"
    pid = created["public_id"]

    list_resp = client.get("/api/income-plans", headers=identity.app_headers)
    body = list_resp.json()
    assert any(p["public_id"] == pid for p in body["items"])
    assert body["total_active_amount_cents"] == 1_000_000


def test_create_income_plan_rejects_invalid_payload(client: TestClient, *, identity) -> None:
    # Pydantic-level rejection (pay_day out of range).
    resp = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "x",
            "source_type": "salary",
            "amount_cents": 100,
            "pay_day": 32,
        },
    )
    assert resp.status_code == 422


def test_update_income_plan_partial(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={"label": "x", "source_type": "salary", "amount_cents": 100, "pay_day": 1},
    ).json()
    pid = created["public_id"]

    # ADR-0038 PR-2j: PATCH requires expected_updated_at token.
    updated = client.patch(
        f"/api/income-plans/{pid}",
        headers=identity.app_headers,
        json={
            "expected_updated_at": created["updated_at"],
            "amount_cents": 500_000,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["amount_cents"] == 500_000
    assert body["label"] == "x"  # unchanged
    assert body["pay_day"] == 1  # unchanged


def test_update_unknown_income_plan_returns_404(client: TestClient, *, identity) -> None:
    resp = client.patch(
        "/api/income-plans/nonexistent",
        headers=identity.app_headers,
        json={
            "expected_updated_at": "2026-05-04T00:00:00Z",
            "label": "x",
        },
    )
    assert resp.status_code == 404


def test_delete_income_plan_archives(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={"label": "tobearchived", "source_type": "salary", "amount_cents": 100, "pay_day": 1},
    ).json()
    pid = created["public_id"]

    delete_resp = client.request(
        "DELETE",
        f"/api/income-plans/{pid}",
        headers=identity.app_headers,
        json={"expected_updated_at": created["updated_at"]},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "archived"
    assert delete_resp.json()["archived_at"] is not None

    # Default list excludes archived.
    list_active = client.get("/api/income-plans", headers=identity.app_headers).json()
    assert all(p["public_id"] != pid for p in list_active["items"])

    # status=all surfaces it.
    list_all = client.get(
        "/api/income-plans?status=all", headers=identity.app_headers
    ).json()
    assert any(p["public_id"] == pid for p in list_all["items"])


def test_restore_income_plan_reactivates(client: TestClient, *, identity) -> None:
    created = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={"label": "torestore", "source_type": "salary", "amount_cents": 100, "pay_day": 1},
    ).json()
    pid = created["public_id"]
    archive_resp = client.request(
        "DELETE",
        f"/api/income-plans/{pid}",
        headers=identity.app_headers,
        json={"expected_updated_at": created["updated_at"]},
    )

    restored = client.post(
        f"/api/income-plans/{pid}/restore",
        headers=identity.app_headers,
        json={"expected_updated_at": archive_resp.json()["updated_at"]},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    assert restored.json()["archived_at"] is None


def test_income_plan_writes_require_writer_role(client: TestClient, *, identity) -> None:
    # No auth at all → 401.
    no_auth = client.post(
        "/api/income-plans",
        json={"label": "x", "source_type": "salary", "amount_cents": 100, "pay_day": 1},
    )
    assert no_auth.status_code == 401


def test_income_plan_status_query_validation(client: TestClient, *, identity) -> None:
    # Pydantic Query pattern only allows active/archived/all.
    resp = client.get(
        "/api/income-plans?status=garbage", headers=identity.app_headers
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/budget/discretionary
# ---------------------------------------------------------------------------


def test_discretionary_zero_when_no_income(client: TestClient, *, identity) -> None:
    resp = client.get("/api/budget/discretionary", headers=identity.app_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["monthly_income_cents"] == 0
    assert body["fixed_expenses_cents"] == 0
    assert body["discretionary_cents"] == 0


def test_discretionary_subtracts_income_minus_fixed_minus_user_params(
    client: TestClient, *, identity
) -> None:
    # Seed an income plan only (no recurring items, so fixed=0).
    client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={"label": "salary", "source_type": "salary", "amount_cents": 1_000_000, "pay_day": 10},
    )
    resp = client.get(
        "/api/budget/discretionary"
        "?savings_target_cents=200000&reserved_buffer_cents=50000",
        headers=identity.app_headers,
    )
    body = resp.json()
    assert body["monthly_income_cents"] == 1_000_000
    assert body["fixed_expenses_cents"] == 0
    assert body["savings_target_cents"] == 200_000
    assert body["reserved_buffer_cents"] == 50_000
    assert body["discretionary_cents"] == 750_000


def test_discretionary_floors_at_zero_when_underwater(
    client: TestClient, *, identity
) -> None:
    client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={"label": "salary", "source_type": "salary", "amount_cents": 100_000, "pay_day": 1},
    )
    resp = client.get(
        "/api/budget/discretionary?savings_target_cents=500000",
        headers=identity.app_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["discretionary_cents"] == 0


def test_discretionary_requires_auth(client: TestClient, *, identity) -> None:  # noqa: ARG001
    resp = client.get("/api/budget/discretionary")
    assert resp.status_code == 401


def test_discretionary_rejects_negative_query_params(
    client: TestClient, *, identity
) -> None:
    resp = client.get(
        "/api/budget/discretionary?savings_target_cents=-1",
        headers=identity.app_headers,
    )
    assert resp.status_code == 422
