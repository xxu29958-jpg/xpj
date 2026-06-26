"""ADR-0038 PR-2j contract tests for ``PATCH /api/goals/{public_id}``.

Goals are per-row PATCH targets shared across surfaces (Android / /web).
Without the token a stale snapshot would silently overwrite a peer
edit; with it the atomic ``UPDATE WHERE updated_at = expected,
status='active'`` rejects stale writes as 409.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Goal
from app.schemas import GoalUpdateRequest
from app.services.goal_service import update_goal


def _idem_headers(identity) -> dict[str, str]:
    """ADR-0042: PATCH now claims an ``Idempotency-Key`` before the OCC claim.
    A fresh UUID per call mints a distinct intent (matching the production
    Android-outbox flow), so a token-bearing request reaches the service."""
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create_goal(client: TestClient, *, identity, name: str = "Goal A") -> dict:
    response = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": name,
            "month": "2026-05",
            "category": "餐饮",
            "target_amount_cents": 5000,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_goal_patch_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    goal = _create_goal(client, identity=identity)
    response = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=identity.app_headers,
        json={"name": "Renamed"},
    )
    assert response.status_code == 422, response.text


def test_goal_patch_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    goal = _create_goal(client, identity=identity)
    bump = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=_idem_headers(identity),
        json={"expected_row_version": goal["row_version"], "name": "First"},
    )
    assert bump.status_code == 200, bump.text

    stale = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=_idem_headers(identity),
        json={"expected_row_version": goal["row_version"], "name": "Stale"},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_goal_patch_unknown_returns_404(client: TestClient, *, identity) -> None:
    # Carries a key so the idempotency claim passes and the handler reaches the
    # 404 (the claim runs before the get_goal lookup; a keyless request would
    # 422 idempotency_key_required first).
    response = client.patch(
        "/api/goals/no-such-public-id",
        headers=_idem_headers(identity),
        json={
            "expected_row_version": 999999,
            "name": "Bogus",
        },
    )
    assert response.status_code == 404, response.text


def test_two_sessions_goal_patch_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    goal = _create_goal(client, identity=identity, name="Race")
    public_id = goal["public_id"]

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(select(Goal).where(Goal.public_id == public_id))
        row_b = session_b.scalar(select(Goal).where(Goal.public_id == public_id))
        assert row_a is not None and row_b is not None
        assert row_a.row_version == row_b.row_version
        shared_version = row_a.row_version

        update_goal(
            session_a,
            tenant_id="owner",
            public_id=public_id,
            payload=GoalUpdateRequest(
                expected_row_version=shared_version,
                name="Writer A",
            ),
        )

        with pytest.raises(AppError) as exc_info:
            update_goal(
                session_b,
                tenant_id="owner",
                public_id=public_id,
                payload=GoalUpdateRequest(
                    expected_row_version=shared_version,
                    name="Writer B",
                ),
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    detail = client.get(
        f"/api/goals/{public_id}", headers=identity.app_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["name"] == "Writer A"


def test_goal_patch_against_archived_returns_409(
    client: TestClient, *, identity
) -> None:
    """Archived goals reject PATCH with the same 409 ``invalid_request``
    code the route used before PR-2j; the token check happens after the
    archived-state pre-check so the existing message UX is preserved."""
    goal = _create_goal(client, identity=identity, name="Archive Target")
    archived = client.post(
        f"/api/goals/{goal['public_id']}/archive",
        headers=identity.app_headers,
    )
    assert archived.status_code == 200, archived.text

    response = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=_idem_headers(identity),
        json={
            "expected_row_version": archived.json()["row_version"],
            "name": "Cannot Edit",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "invalid_request"


def test_goal_restore_reactivates_archived(
    client: TestClient, *, identity
) -> None:
    """ADR-0051 recycle-bin restore: an archived spending_limit goal restores to
    ``active`` and reappears in the active list."""
    goal = _create_goal(client, identity=identity, name="Restore Me")
    archived = client.post(
        f"/api/goals/{goal['public_id']}/archive", headers=identity.app_headers
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    restored = client.post(
        f"/api/goals/{goal['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": archived.json()["row_version"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"
    assert restored.json()["archived_at"] is None

    visible = client.get("/api/goals?month=2026-05", headers=identity.app_headers)
    assert [item["public_id"] for item in visible.json()["items"]] == [goal["public_id"]]


def test_goal_restore_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    goal = _create_goal(client, identity=identity, name="Stale Restore")
    stale_token = goal["row_version"]
    archived = client.post(
        f"/api/goals/{goal['public_id']}/archive", headers=identity.app_headers
    )
    assert archived.status_code == 200, archived.text
    # archive bumped row_version → the pre-archive token is stale for the
    # now-archived row, so restore must 409 rather than flip it.
    stale = client.post(
        f"/api/goals/{goal['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": stale_token},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"
