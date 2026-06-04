"""ADR-0038 PR-2j contract tests for ``PATCH /api/income-plans/{public_id}``.

Mirror of :file:`test_goal_optimistic_concurrency.py` — per-row PATCH,
atomic ``UPDATE WHERE updated_at = expected, status='active'``, stale
snapshot → 409 ``state_conflict``. Archived plans still surface the
existing "请先恢复" message via the status filter.
"""

from __future__ import annotations

from uuid import uuid4

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


def _idem_headers(identity) -> dict[str, str]:
    """ADR-0042: PATCH now claims an ``Idempotency-Key`` before the OCC claim.
    A fresh UUID per call mints a distinct intent, so a token-bearing request
    reaches the service (archive/restore are unchanged — still keyless)."""
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


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
        headers=_idem_headers(identity),
        json={
            "expected_row_version": plan["row_version"],
            "amount_cents": 1_100_000,
        },
    )
    assert bump.status_code == 200, bump.text

    stale = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=_idem_headers(identity),
        json={
            "expected_row_version": plan["row_version"],
            "amount_cents": 1_200_000,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_income_plan_patch_unknown_returns_404(
    client: TestClient, *, identity
) -> None:
    # Carries a key so the idempotency claim passes and the handler reaches the
    # 404 (a keyless request would 422 idempotency_key_required first).
    response = client.patch(
        "/api/income-plans/no-such-public-id",
        headers=_idem_headers(identity),
        json={
            "expected_row_version": 999999,
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
        assert row_a.row_version == row_b.row_version
        shared_version = row_a.row_version

        update_income_plan(
            session_a,
            tenant_id="owner",
            public_id=public_id,
            expected_row_version=shared_version,
            amount_cents=1_500_000,
        )

        with pytest.raises(AppError) as exc_info:
            update_income_plan(
                session_b,
                tenant_id="owner",
                public_id=public_id,
                expected_row_version=shared_version,
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
        current = db.scalar(
            select(MonthlyIncomePlan).where(
                MonthlyIncomePlan.public_id == plan["public_id"]
            )
        )
        archive_income_plan(
            db,
            tenant_id="owner",
            public_id=plan["public_id"],
            expected_row_version=current.row_version,
        )

    response = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=_idem_headers(identity),
        json={
            "expected_row_version": plan["row_version"],
            "amount_cents": 999,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"


def test_income_plan_archive_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    response = client.request(
        "DELETE",
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={},
    )
    assert response.status_code == 422, response.text


def test_income_plan_archive_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    # PATCH bumps updated_at so the create-time token goes stale while the
    # plan is still active — the archive must then 409 rather than flip it.
    bump = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=_idem_headers(identity),
        json={"expected_row_version": plan["row_version"], "amount_cents": 1_100_000},
    )
    assert bump.status_code == 200, bump.text
    stale = client.request(
        "DELETE",
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": plan["row_version"]},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_income_plan_restore_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    archived = client.request(
        "DELETE",
        f"/api/income-plans/{plan['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": plan["row_version"]},
    )
    assert archived.status_code == 200, archived.text
    # Pre-archive token is stale for the now-archived row → restore 409.
    stale = client.post(
        f"/api/income-plans/{plan['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": plan["row_version"]},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_two_sessions_archive_race_idempotent_no_double_write(
    client: TestClient, *, identity
) -> None:
    """Two sessions hold the same pre-archive token. session_a archives;
    session_b's stale claim then matches 0 rows (status no longer 'active'),
    rolls back, re-reads the now-archived row and returns it unchanged — no
    409, no second ``archived_at`` write.

    NB: because ``SessionLocal`` is ``expire_on_commit=False``, session_b's
    ``_require_plan`` returns its stale identity-mapped 'active' row, so this
    exercises the **rollback-recovery** branch (rowcount=0 → re-read archived),
    NOT the same-session early-return — that path is covered separately by
    ``test_archive_is_idempotent``. Either way it asserts the idempotent
    archive contract, distinct from PATCH where the second racing writer 409s.
    """
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
        assert row_a.row_version == row_b.row_version
        shared = row_a.row_version

        first = archive_income_plan(
            session_a, tenant_id="owner", public_id=public_id,
            expected_row_version=shared,
        )
        assert first.status == "archived"
        first_archived_at = first.archived_at

        second = archive_income_plan(
            session_b, tenant_id="owner", public_id=public_id,
            expected_row_version=shared,
        )
        assert second.status == "archived"
        assert second.archived_at == first_archived_at
    finally:
        session_a.close()
        session_b.close()


def test_income_plan_restore_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    plan = _create_plan(client, identity=identity)
    response = client.post(
        f"/api/income-plans/{plan['public_id']}/restore",
        headers=identity.app_headers,
        json={},
    )
    assert response.status_code == 422, response.text


def test_income_plan_archive_unknown_returns_404(
    client: TestClient, *, identity
) -> None:
    response = client.request(
        "DELETE",
        "/api/income-plans/no-such-public-id",
        headers=identity.app_headers,
        json={"expected_row_version": 999999},
    )
    assert response.status_code == 404, response.text


def test_income_plan_restore_unknown_returns_404(
    client: TestClient, *, identity
) -> None:
    response = client.post(
        "/api/income-plans/no-such-public-id/restore",
        headers=identity.app_headers,
        json={"expected_row_version": 999999},
    )
    assert response.status_code == 404, response.text
