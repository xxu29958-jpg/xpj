"""ADR-0042 Slice F: request-idempotency for the goals / income-plan PATCH
mutations (``PATCH /api/goals/{public_id}`` + ``PATCH /api/income-plans/
{public_id}``).

Same uniform contract as Slices B / D-1 / D-2 / E: every outbox-routed mutate
route claims an ``Idempotency-Key`` (via the shared ``claim_idempotent_request``)
BEFORE its OCC ``row_version`` claim. Both ops re-serialise the *current*
resource on a HIT — goal via ``get_goal_response`` (a timezone-aware spend
re-aggregation), income-plan via ``get_income_plan`` + ``_to_response`` — so a
committed-but-unseen replay with a now-stale token returns canonical state,
never the false-409 the OCC claim would otherwise raise.

These route tests pin the wiring + the false-409 fix per op; the helper
internals are already covered by Slice B's unit tests.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import ApiIdempotencyKey
from app.schemas import GoalUpdateRequest, IncomePlanUpdateRequest
from app.services.idempotency import (
    IDEMPOTENCY_STATUS_IN_PROGRESS,
    fingerprint_request,
)
from app.services.time_service import now_utc

if TYPE_CHECKING:
    from tests._infra.identity import TestIdentity


# ---------------------------------------------------------------------------
# setup helpers — each creates a fresh resource and returns the bits a mutate
# request needs (target public_id + current row_version).


def _create_goal(
    client: TestClient, *, identity: TestIdentity, name: str = "Idem Goal", category: str = "餐饮"
) -> dict:
    resp = client.post(
        "/api/goals",
        headers=identity.app_headers,
        json={
            "name": name,
            "month": "2026-05",
            "category": category,
            "target_amount_cents": 5000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_plan(
    client: TestClient, *, identity: TestIdentity, label: str = "Idem 工资"
) -> dict:
    resp = client.post(
        "/api/income-plans",
        headers=identity.app_headers,
        json={
            "label": label,
            "source_type": "salary",
            "amount_cents": 1_000_000,
            "pay_day": 10,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# A request descriptor: (method, url, json-body) with a valid token but NO key.
def _update_goal_request(client: TestClient, *, identity: TestIdentity):
    goal = _create_goal(client, identity=identity)
    return (
        "PATCH",
        f"/api/goals/{goal['public_id']}",
        {"target_amount_cents": 6000, "expected_row_version": goal["row_version"]},
    )


def _update_income_plan_request(client: TestClient, *, identity: TestIdentity):
    plan = _create_plan(client, identity=identity)
    return (
        "PATCH",
        f"/api/income-plans/{plan['public_id']}",
        {"amount_cents": 1_200_000, "expected_row_version": plan["row_version"]},
    )


_REQUEST_BUILDERS = {
    "update_goal": _update_goal_request,
    "update_income_plan": _update_income_plan_request,
}


# ---------------------------------------------------------------------------
# (a) header-required across both ops


@pytest.mark.parametrize("operation", sorted(_REQUEST_BUILDERS))
def test_mutation_requires_idempotency_key(
    client: TestClient, identity: TestIdentity, operation: str
) -> None:
    """Both goals/income-plan PATCH routes reject a keyless request with 422 —
    the missing-key guard runs before the OCC claim, so a valid body (fresh
    token) still 422s ``idempotency_key_required``."""
    method, url, body = _REQUEST_BUILDERS[operation](client, identity=identity)
    resp = client.request(method, url, headers=identity.app_headers, json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"] == "idempotency_key_required"


# ---------------------------------------------------------------------------
# (b) committed-but-unseen replay → canonical (both ops, distinct HIT paths)


def test_update_goal_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen: the SAME key + SAME now-stale token re-serialises
    the (already-updated) goal via ``get_goal_response`` rather than the
    false-409 the OCC claim would raise on the bumped row_version."""
    goal = _create_goal(client, identity=identity)
    v0 = goal["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"target_amount_cents": 6000, "expected_row_version": v0}

    first = client.patch(f"/api/goals/{goal['public_id']}", headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()["target_amount_cents"] == 6000
    v1 = first.json()["row_version"]
    assert v1 != v0

    replay = client.patch(f"/api/goals/{goal['public_id']}", headers=headers, json=body)
    assert replay.status_code == 200, replay.text  # HIT, not 409
    assert replay.json()["target_amount_cents"] == 6000
    assert replay.json()["row_version"] == v1  # canonical, not re-applied


def test_update_income_plan_replay_same_key_returns_canonical_not_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Committed-but-unseen for the income-plan PATCH — its HIT re-serialises
    via ``get_income_plan`` + ``_to_response``, a DISTINCT canonical path from
    goal-update (``get_goal_response``). Same key + same now-stale token returns
    the canonical (already-updated) plan, not the false-409 the OCC would
    raise."""
    plan = _create_plan(client, identity=identity)
    v0 = plan["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"amount_cents": 1_200_000, "expected_row_version": v0}

    first = client.patch(
        f"/api/income-plans/{plan['public_id']}", headers=headers, json=body
    )
    assert first.status_code == 200, first.text
    assert first.json()["amount_cents"] == 1_200_000
    v1 = first.json()["row_version"]
    assert v1 != v0

    replay = client.patch(
        f"/api/income-plans/{plan['public_id']}", headers=headers, json=body
    )
    assert replay.status_code == 200, replay.text  # HIT via get_income_plan, not 409
    assert replay.json()["amount_cents"] == 1_200_000
    assert replay.json()["row_version"] == v1  # canonical, not re-applied


# ---------------------------------------------------------------------------
# (c) stale-token-different-key → 409 state_conflict (idempotency didn't weaken OCC)


def test_update_goal_stale_token_with_different_key_still_409s(
    client: TestClient, identity: TestIdentity
) -> None:
    """Negative control: a DIFFERENT key with the same now-stale token is a
    genuine concurrent writer → OCC 409 stays intact."""
    goal = _create_goal(client, identity=identity)
    v0 = goal["row_version"]
    body = {"target_amount_cents": 6000, "expected_row_version": v0}

    first = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert first.status_code == 200, first.text

    stale = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


def test_update_income_plan_stale_token_with_different_key_still_409s(
    client: TestClient, identity: TestIdentity
) -> None:
    """Same negative control for income-plan: different key + same stale token
    → genuine OCC 409."""
    plan = _create_plan(client, identity=identity)
    v0 = plan["row_version"]
    body = {"amount_cents": 1_200_000, "expected_row_version": v0}

    first = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert first.status_code == 200, first.text

    stale = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json=body,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "state_conflict"


# ---------------------------------------------------------------------------
# (d) in-progress → 409 (hand-built fingerprint matching the route exactly)


def test_update_goal_in_progress_returns_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """A fresh in_progress placeholder (same key + matching fingerprint) blocks
    a concurrent same-key request → 409 idempotency_key_in_progress. The
    fingerprint body is computed from the SAME request model the route parses
    (``GoalUpdateRequest.model_dump(mode='json', exclude_unset, exclude
    expected_row_version)``) so the hand-built fingerprint matches exactly."""
    goal = _create_goal(client, identity=identity)
    v0 = goal["row_version"]
    key = str(uuid4())
    payload = GoalUpdateRequest(expected_row_version=v0, target_amount_cents=6000)
    fingerprint = fingerprint_request(
        operation="update_goal",
        target_id=goal["public_id"],
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=v0,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="update_goal",
                target_type="goal",
                target_id=goal["public_id"],
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"target_amount_cents": 6000, "expected_row_version": v0},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


def test_update_income_plan_in_progress_returns_409(
    client: TestClient, identity: TestIdentity
) -> None:
    """Same in_progress block for income-plan, fingerprint built from
    ``IncomePlanUpdateRequest`` exactly as the route computes it."""
    plan = _create_plan(client, identity=identity)
    v0 = plan["row_version"]
    key = str(uuid4())
    payload = IncomePlanUpdateRequest(expected_row_version=v0, amount_cents=1_200_000)
    fingerprint = fingerprint_request(
        operation="update_income_plan",
        target_id=plan["public_id"],
        body=payload.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_row_version"}
        ),
        expected_row_version=v0,
    )
    with SessionLocal() as db:
        db.add(
            ApiIdempotencyKey(
                tenant_id="owner",
                idempotency_key=key,
                operation="update_income_plan",
                target_type="income_plan",
                target_id=plan["public_id"],
                request_fingerprint=fingerprint,
                status=IDEMPOTENCY_STATUS_IN_PROGRESS,
                created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.commit()

    resp = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers={**identity.app_headers, "Idempotency-Key": key},
        json={"amount_cents": 1_200_000, "expected_row_version": v0},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"] == "idempotency_key_in_progress"


# ---------------------------------------------------------------------------
# (e) reuse-422 (same key, different request body)


def test_update_goal_same_key_different_body_is_reused_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.7: same key, different request (a different ``target_amount_cents``)
    → 422 idempotency_key_reused. The first call succeeded, so the second's
    mismatching fingerprint is rejected before any mutation."""
    goal = _create_goal(client, identity=identity)
    v0 = goal["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=headers,
        json={"target_amount_cents": 6000, "expected_row_version": v0},
    )
    assert first.status_code == 200, first.text

    reused = client.patch(
        f"/api/goals/{goal['public_id']}",
        headers=headers,
        json={"target_amount_cents": 7000, "expected_row_version": v0},  # different intent
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"


def test_update_income_plan_same_key_different_body_is_reused_422(
    client: TestClient, identity: TestIdentity
) -> None:
    """§4.7 for income-plan: same key, different ``amount_cents`` → 422
    idempotency_key_reused, never silently applying the second intent."""
    plan = _create_plan(client, identity=identity)
    v0 = plan["row_version"]
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}

    first = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=headers,
        json={"amount_cents": 1_200_000, "expected_row_version": v0},
    )
    assert first.status_code == 200, first.text

    reused = client.patch(
        f"/api/income-plans/{plan['public_id']}",
        headers=headers,
        json={"amount_cents": 1_300_000, "expected_row_version": v0},  # different intent
    )
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"] == "idempotency_key_reused"
