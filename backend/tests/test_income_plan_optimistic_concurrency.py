"""ADR-0038 PR-2j contract tests for ``PATCH /api/income-plans/{public_id}``.

Mirror of :file:`test_goal_optimistic_concurrency.py` — per-row PATCH,
atomic ``UPDATE WHERE updated_at = expected, status='active'``, stale
snapshot → 409 ``state_conflict``. Archived plans still surface the
existing "请先恢复" message via the status filter.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import MonthlyIncomePlan
from app.services.income_plan_service import (
    archive_income_plan,
    update_income_plan,
)


def _create_plan(client: TestClient, *, identity, label: str = "工资 A") -> dict:
    response = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": label,
            "source_type": "salary",
            "amount_cents": 1_000_000,
            "pay_day": 10,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_income_plan_patch_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    response = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={"amount_cents": 1_200_000},
    )
    assert response.status_code == 422, response.text


def test_income_plan_patch_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    bump = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_updated_at": plan["updated_at"],
            "amount_cents": 1_100_000,
        },
    )
    assert bump.status_code == 200, bump.text

    stale = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_updated_at": plan["updated_at"],
            "amount_cents": 1_200_000,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_income_plan_patch_unknown_returns_404(
    client: TestClient, *, identity
) -> None:
    response = client.patch(
        "/api/income-plans/no-such-public-id",
        headers=identity.app_headers,
        json={
            "expected_updated_at": "2026-05-04T00:00:00Z",
            "label": "Bogus",
        },
    )
    assert response.status_code == 404, response.text


def test_two_sessions_income_plan_patch_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    public_id = plan["public_id"]

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(
            select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == public_id)
        )
        row_b = session_b.scalar(
            select(MonthlyIncomePlan).where(MonthlyIncomePlan.public_id == public_id)
        )
        assert row_a is not None and row_b is not None
        assert row_a.updated_at == row_b.updated_at
        shared_version = row_a.updated_at

        update_income_plan(
            session_a,
            tenant_id="owner",
            public_id=public_id,
            expected_updated_at=shared_version,
            amount_cents=1_500_000,
        )

        with pytest.raises(AppError) as exc_info:
            update_income_plan(
                session_b,
                tenant_id="owner",
                public_id=public_id,
                expected_updated_at=shared_version,
                amount_cents=1_700_000,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    final = client.get(
        "/api/income-plans?status=active", headers=identity.app_headers
    )
    matched = [
        item for item in final.json()["items"] if item["public_id"] == public_id
    ]
    assert len(matched) == 1
    assert matched[0]["amount_cents"] == 1_500_000


def test_archived_plan_patch_preserves_existing_409(
    client: TestClient, *, identity
) -> None:
    """An archived plan still rejects PATCH with the existing
    ``state_conflict`` + "已归档" message UX. The status filter inside
    ``claim_row_with_token`` matches ``status='active'`` only, so the
    archived path raises before the token check ever runs."""
    plan = _create_plan(client, identity=identity, label="To Archive")
    with SessionLocal() as db:
        archive_income_plan(db, tenant_id="owner", public_id=plan["public_id"])

    response = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_updated_at": plan["updated_at"],
            "amount_cents": 999,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"
