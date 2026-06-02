"""ADR-0038 PR-2e contract tests for merchant_alias PATCH / DELETE.

Mirrors the per-row optimistic-concurrency contract the rest of v1.3
PR-2 covers: missing token → 422, stale token → 409, two-session race
→ first writer wins, ``state_conflict`` for the loser.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import MerchantAlias
from app.services.merchant_alias_service import (
    delete_merchant_alias,
    update_merchant_alias,
)


def _create_alias(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/merchants/aliases",
        headers=headers,
        json={"canonical_merchant": "星巴克", "alias": "STARBUCKS 国贸店"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_merchant_alias_patch_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    created = _create_alias(client, identity.app_headers)
    response = client.patch(
        f"/api/merchants/aliases/{created['public_id']}",
        headers=identity.app_headers,
        json={"enabled": False},
    )
    assert response.status_code == 422, response.text


def test_merchant_alias_delete_without_token_returns_422(
    client: TestClient, *, identity
) -> None:
    created = _create_alias(client, identity.app_headers)
    response = client.request(
        "DELETE",
        f"/api/merchants/aliases/{created['public_id']}",
        headers=identity.app_headers,
        json={},
    )
    assert response.status_code == 422, response.text


def test_merchant_alias_patch_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    created = _create_alias(client, identity.app_headers)
    # Mutate the alias once so the originally-seen ``updated_at`` is stale.
    bump = client.patch(
        f"/api/merchants/aliases/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "enabled": False,
        },
    )
    assert bump.status_code == 200, bump.text

    response = client.patch(
        f"/api/merchants/aliases/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "enabled": True,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"


def test_merchant_alias_delete_with_stale_token_returns_409(
    client: TestClient, *, identity
) -> None:
    created = _create_alias(client, identity.app_headers)
    bump = client.patch(
        f"/api/merchants/aliases/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "enabled": False,
        },
    )
    assert bump.status_code == 200, bump.text

    response = client.request(
        "DELETE",
        f"/api/merchants/aliases/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"] == "state_conflict"


def test_two_sessions_patch_alias_race_only_first_writer_wins(
    client: TestClient, *, identity
) -> None:
    created = _create_alias(client, identity.app_headers)
    public_id = created["public_id"]

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(
            select(MerchantAlias).where(MerchantAlias.public_id == public_id)
        )
        row_b = session_b.scalar(
            select(MerchantAlias).where(MerchantAlias.public_id == public_id)
        )
        assert row_a is not None and row_b is not None
        assert row_a.row_version == row_b.row_version
        shared_version = row_a.row_version

        update_merchant_alias(
            session_a,
            row_a,
            expected_row_version=shared_version,
            enabled=False,
        )

        with pytest.raises(AppError) as exc_info:
            update_merchant_alias(
                session_b,
                row_b,
                expected_row_version=shared_version,
                enabled=True,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    final = client.get("/api/merchants/aliases", headers=identity.app_headers)
    assert final.status_code == 200, final.text
    matched = [item for item in final.json()["items"] if item["public_id"] == public_id]
    assert len(matched) == 1
    assert matched[0]["enabled"] is False


def test_delete_alias_with_stale_token_after_concurrent_patch(
    client: TestClient, *, identity
) -> None:
    """Two-session race for DELETE: session A toggles enabled, session B
    tries to DELETE with the original snapshot. DELETE must lose."""
    created = _create_alias(client, identity.app_headers)
    public_id = created["public_id"]

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(
            select(MerchantAlias).where(MerchantAlias.public_id == public_id)
        )
        row_b = session_b.scalar(
            select(MerchantAlias).where(MerchantAlias.public_id == public_id)
        )
        assert row_a is not None and row_b is not None
        shared_version = row_a.row_version

        update_merchant_alias(
            session_a,
            row_a,
            expected_row_version=shared_version,
            enabled=False,
        )

        with pytest.raises(AppError) as exc_info:
            delete_merchant_alias(
                session_b,
                row_b,
                expected_row_version=shared_version,
            )
        assert exc_info.value.error == "state_conflict"
        assert exc_info.value.status_code == 409
    finally:
        session_a.close()
        session_b.close()

    detail = client.get("/api/merchants/aliases", headers=identity.app_headers)
    matched = [item for item in detail.json()["items"] if item["public_id"] == public_id]
    assert len(matched) == 1


def test_delete_then_patch_race_resolves_to_404(
    client: TestClient, *, identity
) -> None:
    """A concurrent delete leaves session B holding an ORM instance whose
    pk + columns are still in the identity map but whose row no longer
    exists. PATCH against that ghost must surface as 404
    ``merchant_alias_not_found`` rather than an opaque SQLAlchemy
    ``ObjectDeletedError`` mid-build (rollback path expires the instance
    and access to ``item.public_id`` would then raise). Mirrors the
    PR-1 ``update_rule`` ObjectDeletedError guard.
    """
    created = _create_alias(client, identity.app_headers)
    public_id = created["public_id"]

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        row_a = session_a.scalar(
            select(MerchantAlias).where(MerchantAlias.public_id == public_id)
        )
        row_b = session_b.scalar(
            select(MerchantAlias).where(MerchantAlias.public_id == public_id)
        )
        assert row_a is not None and row_b is not None
        shared_version = row_a.row_version

        # Session A wins via DELETE. The row is gone.
        delete_merchant_alias(
            session_a,
            row_a,
            expected_row_version=shared_version,
        )

        # Force session_b's row to be considered deleted in the identity
        # map so reaching for ``row_b.public_id`` after rollback would
        # raise ObjectDeletedError without the guard.
        session_b.expire(row_b)

        with pytest.raises(AppError) as exc_info:
            update_merchant_alias(
                session_b,
                row_b,
                expected_row_version=shared_version,
                enabled=False,
            )
        assert exc_info.value.error == "merchant_alias_not_found"
        assert exc_info.value.status_code == 404
    finally:
        session_a.close()
        session_b.close()


def test_patch_unknown_alias_returns_404(client: TestClient, *, identity) -> None:
    response = client.patch(
        "/api/merchants/aliases/no-such-public-id",
        headers=identity.app_headers,
        json={
            "expected_row_version": 999999,
            "enabled": False,
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "merchant_alias_not_found"


def test_delete_unknown_alias_returns_404(client: TestClient, *, identity) -> None:
    response = client.request(
        "DELETE",
        "/api/merchants/aliases/no-such-public-id",
        headers=identity.app_headers,
        json={"expected_row_version": 999999},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"] == "merchant_alias_not_found"
