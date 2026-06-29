"""ADR-0053 merchant catalog backend contract."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember, MerchantAlias, RecurringItem
from app.services.merchant_catalog_service import clean_merchant_catalog_status
from app.services.merchant_service import normalize_merchant
from app.services.time_service import now_utc


def _create_catalog(
    client: TestClient,
    headers: dict[str, str],
    *,
    display_name: str = "Starbucks",
    status: str = "active",
) -> dict:
    response = client.post(
        "/api/merchants/catalog",
        headers=headers,
        json={"display_name": display_name, "status": status},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()


def _seed_historical_expense(*, merchant: str = "Starbucks") -> None:
    with SessionLocal() as db:
        now = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=1800,
                merchant=merchant,
                category="Coffee",
                status="confirmed",
                expense_time=now,
                confirmed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def _seed_enabled_alias_target(*, merchant_key: str) -> None:
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            MerchantAlias(
                tenant_id="owner",
                canonical_merchant="Anchor Store",
                canonical_key=merchant_key,
                alias="Anchor Alias",
                alias_key=normalize_merchant("Anchor Alias"),
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()


def _disable_alias_and_seed_recurring(*, merchant_key: str) -> None:
    with SessionLocal() as db:
        alias = db.scalar(
            select(MerchantAlias)
            .where(MerchantAlias.tenant_id == "owner")
            .where(MerchantAlias.canonical_key == merchant_key)
        )
        assert alias is not None
        alias.enabled = False
        db.add(
            RecurringItem(
                tenant_id="owner",
                merchant_key=merchant_key,
                merchant_name="Anchor Store",
                baseline_amount_cents=1800,
                last_amount_cents=1800,
                occurrence_count=3,
                status="active",
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )
        db.commit()


def _archive_recurring(*, merchant_key: str) -> None:
    with SessionLocal() as db:
        recurring = db.scalar(
            select(RecurringItem)
            .where(RecurringItem.tenant_id == "owner")
            .where(RecurringItem.merchant_key == merchant_key)
        )
        assert recurring is not None
        recurring.status = "archived"
        recurring.archived_at = now_utc()
        db.commit()


def test_merchant_catalog_crud_soft_delete_and_recycle_restore(
    client: TestClient, *, identity
) -> None:
    _seed_historical_expense()
    created = _create_catalog(client, identity.app_headers)
    assert created["display_name"] == "Starbucks"
    assert created["merchant_key"] == "starbucks"
    assert created["usage_count"] == 1
    assert created["status"] == "active"

    listed = client.get("/api/merchants/catalog", headers=identity.app_headers)
    assert listed.status_code == 200
    assert [item["public_id"] for item in listed.json()["items"]] == [
        created["public_id"]
    ]

    hidden = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"], "status": "hidden"},
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "hidden"

    active_only = client.get(
        "/api/merchants/catalog?include_hidden=false",
        headers=identity.app_headers,
    )
    assert active_only.status_code == 200
    assert active_only.json()["items"] == []

    deleted = client.request(
        "DELETE",
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": hidden.json()["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None
    assert (
        client.get("/api/merchants/catalog", headers=identity.app_headers).json()[
            "items"
        ]
        == []
    )

    recycle = client.get("/api/recycle-bin", headers=identity.app_headers)
    assert recycle.status_code == 200
    assert any(
        item["kind"] == "merchant_catalog"
        and item["resource_id"] == created["public_id"]
        and item["title"] == "Starbucks"
        for item in recycle.json()["items"]
    )

    restored = client.post(
        "/api/recycle-bin/restore",
        headers=identity.app_headers,
        json={
            "kind": "merchant_catalog",
            "resource_id": created["public_id"],
            "expected_row_version": deleted.json()["row_version"],
        },
    )
    assert restored.status_code == 200, restored.text
    relisted = client.get("/api/merchants/catalog", headers=identity.app_headers)
    assert [item["public_id"] for item in relisted.json()["items"]] == [
        created["public_id"]
    ]


def test_merchant_catalog_is_ledger_isolated_and_conflict_checked(
    client: TestClient, *, identity
) -> None:
    owner = _create_catalog(client, identity.app_headers, display_name="Shared Store")
    tester = _create_catalog(
        client,
        identity.gray_app_headers,
        display_name="Shared Store",
    )
    assert owner["public_id"] != tester["public_id"]

    duplicate = client.post(
        "/api/merchants/catalog",
        headers=identity.app_headers,
        json={"display_name": " shared   store "},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "state_conflict"

    cross_patch = client.patch(
        f"/api/merchants/catalog/{owner['public_id']}",
        headers=identity.gray_app_headers,
        json={"expected_row_version": owner["row_version"], "status": "hidden"},
    )
    assert cross_patch.status_code == 404
    assert cross_patch.json()["error"] == "not_found"


def test_viewer_cannot_mutate_merchant_catalog(
    client: TestClient, *, identity
) -> None:
    created = _create_catalog(client, identity.app_headers)
    _demote_owner_ledger_to_viewer()

    checks = [
        client.post(
            "/api/merchants/catalog",
            headers=identity.app_headers,
            json={"display_name": "KFC"},
        ),
        client.patch(
            f"/api/merchants/catalog/{created['public_id']}",
            headers=identity.app_headers,
            json={"expected_row_version": created["row_version"], "status": "hidden"},
        ),
        client.request(
            "DELETE",
            f"/api/merchants/catalog/{created['public_id']}",
            headers=identity.app_headers,
            json={"expected_row_version": created["row_version"]},
        ),
    ]
    for response in checks:
        assert response.status_code == 403
        assert response.json()["error"] == "permission_denied"

    listed = client.get("/api/merchants/catalog", headers=identity.app_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_merchant_catalog_delete_blocks_live_config_not_historical_facts(
    client: TestClient, *, identity
) -> None:
    created = _create_catalog(client, identity.app_headers, display_name="Anchor Store")
    merchant_key = normalize_merchant("Anchor Store")
    assert clean_merchant_catalog_status(" hidden ") == "hidden"
    _seed_enabled_alias_target(merchant_key=merchant_key)

    blocked_by_alias = client.request(
        "DELETE",
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"]},
    )
    assert blocked_by_alias.status_code == 409
    assert blocked_by_alias.json()["error"] == "state_conflict"

    _disable_alias_and_seed_recurring(merchant_key=merchant_key)

    blocked_by_recurring = client.request(
        "DELETE",
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"]},
    )
    assert blocked_by_recurring.status_code == 409
    assert blocked_by_recurring.json()["error"] == "state_conflict"

    _archive_recurring(merchant_key=merchant_key)
    _seed_historical_expense(merchant="Anchor Store")

    deleted = client.request(
        "DELETE",
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None


def test_merchant_catalog_stale_tokens_return_conflict(
    client: TestClient, *, identity
) -> None:
    created = _create_catalog(client, identity.app_headers)
    updated = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"], "status": "hidden"},
    )
    assert updated.status_code == 200, updated.text

    stale_patch = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"], "status": "active"},
    )
    assert stale_patch.status_code == 409
    assert stale_patch.json()["error"] == "state_conflict"

    stale_delete = client.request(
        "DELETE",
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": created["row_version"]},
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["error"] == "state_conflict"
