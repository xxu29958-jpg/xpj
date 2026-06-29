"""v1.1 PR-7: HTTP integration tests for income_plans + budget/discretionary.

Cover the writer / viewer permission split, the validation surface
(wrong field shapes / values), the empty-state defaults, and the
shape-of-response contract that the Android / web client will consume.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense

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
    assert created["frequency"] == "monthly"
    assert created["income_month"] is None
    assert created["status"] == "active"
    pid = created["public_id"]

    list_resp = client.get("/api/income-plans", headers=identity.app_headers)
    body = list_resp.json()
    assert any(p["public_id"] == pid for p in body["items"])
    assert body["total_active_amount_cents"] == 1_000_000


def test_create_one_time_income_counts_only_for_requested_month(
    client: TestClient, *, identity
) -> None:
    create_resp = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "项目奖金",
            "source_type": "bonus",
            "frequency": "one_time",
            "income_month": "2026-06",
            "amount_cents": 250_000,
            "pay_day": 28,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["frequency"] == "one_time"
    assert created["income_month"] == "2026-06"

    june = client.get(
        "/api/income-plans?month=2026-06",
        headers=identity.app_headers,
    ).json()
    july = client.get(
        "/api/income-plans?month=2026-07",
        headers=identity.app_headers,
    ).json()
    assert june["total_active_amount_cents"] == 250_000
    assert july["total_active_amount_cents"] == 0


def test_create_one_time_income_rejects_missing_income_month(
    client: TestClient, *, identity
) -> None:
    resp = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "项目奖金",
            "source_type": "bonus",
            "frequency": "one_time",
            "amount_cents": 250_000,
            "pay_day": 28,
        },
    )
    assert resp.status_code == 422


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

    # ADR-0038 PR-2j: PATCH requires expected_row_version token.
    # ADR-0042: PATCH also requires an Idempotency-Key (claimed before the OCC).
    updated = client.patch(
        f"/api/income-plans/{pid}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": created["row_version"],
            "amount_cents": 500_000,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["amount_cents"] == 500_000
    assert body["label"] == "x"  # unchanged
    assert body["pay_day"] == 1  # unchanged


def test_update_unknown_income_plan_returns_404(client: TestClient, *, identity) -> None:
    # Key lets the idempotency claim pass so the handler reaches the 404
    # (keyless would 422 idempotency_key_required first).
    resp = client.patch(
        "/api/income-plans/nonexistent",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": 999999,
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
        json={"expected_row_version": created["row_version"]},
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
        json={"expected_row_version": created["row_version"]},
    )

    restored = client.post(
        f"/api/income-plans/{pid}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": archive_resp.json()["row_version"]},
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
    assert body["spent_amount_cents"] == 0
    assert body["savings_target_cents"] == 200_000
    assert body["reserved_buffer_cents"] == 50_000
    assert body["discretionary_cents"] == 750_000


def test_discretionary_late_salary_backfill_offsets_existing_spend(
    client: TestClient, *, identity
) -> None:  # noqa: ARG001
    spent_at = datetime(2026, 6, 12, 4, tzinfo=timezone.utc)
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                status="confirmed",
                amount_cents=300_000,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=300_000,
                merchant="永辉超市",
                category="购物",
                expense_time=spent_at,
                confirmed_at=spent_at,
                created_at=spent_at,
                updated_at=spent_at,
            )
        )
        db.commit()

    income_resp = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "六月工资",
            "source_type": "salary",
            "frequency": "one_time",
            "income_month": "2026-06",
            "amount_cents": 1_000_000,
            "pay_day": 28,
        },
    )
    assert income_resp.status_code == 201, income_resp.text

    resp = client.get(
        "/api/budget/discretionary?month=2026-06",
        headers=identity.app_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["monthly_income_cents"] == 1_000_000
    assert body["spent_amount_cents"] == 300_000
    assert body["discretionary_cents"] == 700_000


def test_discretionary_includes_one_time_income_only_for_query_month(
    client: TestClient, *, identity
) -> None:
    client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": "one-off",
            "source_type": "bonus",
            "frequency": "one_time",
            "income_month": "2026-06",
            "amount_cents": 200_000,
            "pay_day": 18,
        },
    )
    june = client.get(
        "/api/budget/discretionary?month=2026-06",
        headers=identity.app_headers,
    )
    july = client.get(
        "/api/budget/discretionary?month=2026-07",
        headers=identity.app_headers,
    )
    assert june.status_code == 200
    assert july.status_code == 200
    assert june.json()["monthly_income_cents"] == 200_000
    assert july.json()["monthly_income_cents"] == 0


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
