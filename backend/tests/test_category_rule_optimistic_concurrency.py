"""ADR-0038 contract tests for category_rule PATCH/DELETE.

The mutation endpoints accept ``expected_row_version`` (required); a
stale value surfaces as ``409 state_conflict`` so the client can
re-read and let the user resolve. PR-1 试点 — only the API surface,
not Android outbox / undo (PR-2+).

The service-level test at the bottom covers the read/read/write/write
race that the HTTP-level replay-after-commit test cannot exercise:
two SQLAlchemy sessions both load the row at version T1, the first
commits to T2, and the second's atomic ``UPDATE WHERE updated_at =
T1`` predicate must be rejected at the DB layer (rowcount=0 → 409).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import CategoryRule
from app.services.rule_service import update_rule


def _create_rule(client: TestClient, *, identity, keyword: str = "TestCafe") -> dict:
    resp = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": keyword,
            "category": "餐饮",
            "enabled": True,
            "priority": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# PATCH


def test_patch_category_rule_with_fresh_updated_at_succeeds(
    client: TestClient, *, identity
) -> None:
    rule = _create_rule(client, identity=identity)
    resp = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={
            "category": "交通",
            "expected_row_version": rule["row_version"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "交通"
    assert resp.json()["updated_at"] != rule["updated_at"]


def test_patch_category_rule_with_stale_updated_at_returns_409(
    client: TestClient, *, identity
) -> None:
    rule = _create_rule(client, identity=identity)
    # First PATCH succeeds and bumps updated_at.
    first = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={
            "category": "交通",
            "expected_row_version": rule["row_version"],
        },
    )
    assert first.status_code == 200
    # Second PATCH replays the original updated_at — now stale.
    stale = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={
            "category": "购物",
            "expected_row_version": rule["row_version"],
        },
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["error"] == "state_conflict"
    assert body["message"]


def test_patch_category_rule_without_expected_row_version_returns_422(
    client: TestClient, *, identity
) -> None:
    rule = _create_rule(client, identity=identity)
    resp = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={"category": "交通"},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# DELETE


def test_delete_category_rule_with_fresh_updated_at_succeeds(
    client: TestClient, *, identity
) -> None:
    rule = _create_rule(client, identity=identity, keyword="DeleteMe")
    resp = client.request(
        "DELETE",
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={"expected_row_version": rule["row_version"]},
    )
    assert resp.status_code == 200, resp.text


def test_delete_category_rule_with_stale_updated_at_returns_409(
    client: TestClient, *, identity
) -> None:
    rule = _create_rule(client, identity=identity, keyword="DeleteStale")
    # First mutate to bump updated_at so the original snapshot is stale.
    first = client.patch(
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={
            "enabled": False,
            "expected_row_version": rule["row_version"],
        },
    )
    assert first.status_code == 200
    # Replay the original updated_at on DELETE — should now 409.
    stale = client.request(
        "DELETE",
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={"expected_row_version": rule["row_version"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "state_conflict"


def test_delete_category_rule_without_expected_row_version_returns_422(
    client: TestClient, *, identity
) -> None:
    rule = _create_rule(client, identity=identity, keyword="DeleteMissingField")
    resp = client.request(
        "DELETE",
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Atomic write/write race — exercised at the service layer with two
# SessionLocal handles so the test does not depend on threaded HTTP
# clients. Pre-PR-1 the implementation was ``rule.updated_at !=
# expected`` in Python, which would have let both writers pass; the
# atomic ``UPDATE WHERE updated_at = expected`` predicate is what
# rejects the second writer here.


def test_two_sessions_seeing_same_updated_at_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    rule_payload = _create_rule(client, identity=identity, keyword="RaceCafe")
    rule_id = int(rule_payload["id"])

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        rule_a = session_a.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        rule_b = session_b.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        assert rule_a is not None and rule_b is not None
        # Both sessions read the same version; this is the read/read
        # half of the race.
        assert rule_a.row_version == rule_b.row_version
        shared_version = rule_a.row_version

        # Writer A commits first — succeeds.
        update_rule(
            session_a,
            rule_a,
            expected_row_version=shared_version,
            category="交通",
        )

        # Writer B still holds its rule with the stale shared_version.
        # Pre-fix this would silently overwrite A's change; post-fix
        # the UPDATE WHERE predicate finds rowcount=0 and we surface
        # state_conflict 409.
        with pytest.raises(AppError) as exc_info:
            update_rule(
                session_b,
                rule_b,
                expected_row_version=shared_version,
                category="购物",
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()


def test_two_sessions_concurrent_delete_then_update_resolves_to_404_or_409(
    client: TestClient, *, identity
) -> None:
    """Variant: writer A deletes, writer B tries to PATCH with the
    pre-delete expected_row_version. The atomic UPDATE finds no row
    (rowcount=0); disambiguation falls through to ``rule_not_found``
    404 because find_rule_for_tenant also returns None."""
    rule_payload = _create_rule(client, identity=identity, keyword="RaceDeleted")
    rule_id = int(rule_payload["id"])

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        rule_a = session_a.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        rule_b = session_b.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        assert rule_a is not None and rule_b is not None
        shared_version = rule_a.row_version

        session_a.delete(rule_a)
        session_a.commit()

        with pytest.raises(AppError) as exc_info:
            update_rule(
                session_b,
                rule_b,
                expected_row_version=shared_version,
                category="购物",
            )
        assert exc_info.value.error == "rule_not_found"
        assert exc_info.value.status_code == 404
    finally:
        session_a.close()
        session_b.close()
