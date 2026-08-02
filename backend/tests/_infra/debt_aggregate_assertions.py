"""Typed end-to-end assertions for aggregate Debt money projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Debt, DebtAdjustment
from app.money_contract import MONEY_MINOR_MAX


def create_repayment_goal(
    client: TestClient,
    app_headers: Mapping[str, str],
    debt_public_id: str,
) -> str:
    goal = client.post(
        "/api/goals",
        headers=app_headers,
        json={
            "name": "聚合金额边界",
            "goal_type": "debt_repayment",
            "debt_public_ids": [debt_public_id],
        },
    )
    assert goal.status_code == 201, goal.json()
    return str(goal.json()["public_id"])


def assert_adjustment_response_loss_recovery(
    client: TestClient,
    app_headers: Mapping[str, str],
    debt: Mapping[str, Any],
) -> int:
    adjustment_headers = {
        **app_headers,
        "Idempotency-Key": str(uuid4()),
    }
    adjustment_payload = {
        "amount_cents": 1,
        "reason": "补记一最小单位",
        "expected_row_version": debt["row_version"],
    }
    first = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=adjustment_headers,
        json=adjustment_payload,
    )
    assert first.status_code == 201, first.text
    assert first.json()["remaining_amount_cents"] == MONEY_MINOR_MAX + 1
    assert first.json()["paid_amount_cents"] == 0
    adjusted_version = int(first.json()["row_version"])

    # Retry the exact original intent after simulated response loss, including
    # its now-stale OCC token. The idempotency hit returns the canonical fold.
    replay = client.post(
        f"/api/debts/{debt['public_id']}/adjustments",
        headers=adjustment_headers,
        json=adjustment_payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["remaining_amount_cents"] == MONEY_MINOR_MAX + 1
    assert replay.json()["row_version"] == adjusted_version
    return adjusted_version


def assert_one_adjustment_fact(debt_public_id: str) -> None:
    with SessionLocal() as db:
        debt_row = db.scalar(select(Debt).where(Debt.public_id == debt_public_id))
        assert debt_row is not None
        adjustment_count = db.scalar(
            select(func.count())
            .select_from(DebtAdjustment)
            .where(DebtAdjustment.debt_id == debt_row.id)
        )
        assert adjustment_count == 1


def assert_aggregate_visible_in_all_read_models(
    client: TestClient,
    app_headers: Mapping[str, str],
    debt_public_id: str,
    goal_public_id: str,
) -> None:
    detail = client.get(
        f"/api/debts/{debt_public_id}",
        headers=app_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["remaining_amount_cents"] == MONEY_MINOR_MAX + 1

    listed = client.get("/api/debts", headers=app_headers)
    assert listed.status_code == 200, listed.text
    listed_debt = next(
        item
        for item in listed.json()["items"]
        if item["public_id"] == debt_public_id
    )
    assert listed_debt["remaining_amount_cents"] == MONEY_MINOR_MAX + 1

    goal_detail = client.get(
        f"/api/goals/{goal_public_id}",
        headers=app_headers,
    )
    assert goal_detail.status_code == 200, goal_detail.text
    linked_debt = goal_detail.json()["debt_repayment"]["linked_debts"][0]
    assert linked_debt["remaining_amount_cents"] == MONEY_MINOR_MAX + 1


def assert_paid_aggregate_crosses_single_command_ceiling(
    client: TestClient,
    app_headers: Mapping[str, str],
    debt_public_id: str,
    adjusted_version: int,
) -> None:
    first_repayment = client.post(
        f"/api/debts/{debt_public_id}/repayments",
        headers={**app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "amount_cents": MONEY_MINOR_MAX,
            "expected_row_version": adjusted_version,
        },
    )
    assert first_repayment.status_code == 201, first_repayment.text
    final_repayment = client.post(
        f"/api/debts/{debt_public_id}/repayments",
        headers={**app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "amount_cents": 1,
            "expected_row_version": first_repayment.json()["row_version"],
        },
    )
    assert final_repayment.status_code == 201, final_repayment.text
    assert final_repayment.json()["paid_amount_cents"] == MONEY_MINOR_MAX + 1
    assert final_repayment.json()["remaining_amount_cents"] == 0
