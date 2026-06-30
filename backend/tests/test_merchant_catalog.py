"""ADR-0053 merchant catalog backend contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.merchant_catalog_guards import (
    WRITABLE_STATUSES as _CATALOG_WRITABLE_STATUSES,
)
from app.services.merchant_catalog_service import clean_merchant_catalog_status
from app.services.merchant_service import normalize_merchant
from tests._infra.merchant_catalog import archive_recurring as _archive_recurring
from tests._infra.merchant_catalog import (
    assert_historical_expense_exists as _assert_historical_expense_exists,
)
from tests._infra.merchant_catalog import create_catalog as _create_catalog
from tests._infra.merchant_catalog import (
    demote_owner_ledger_to_viewer as _demote_owner_ledger_to_viewer,
)
from tests._infra.merchant_catalog import (
    disable_alias_and_seed_recurring as _disable_alias_and_seed_recurring,
)
from tests._infra.merchant_catalog import (
    seed_enabled_alias_target as _seed_enabled_alias_target,
)
from tests._infra.merchant_catalog import seed_historical_expense as _seed_historical_expense


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
    duplicate_body = duplicate.json()
    assert duplicate_body["error"] == "state_conflict"
    assert duplicate_body["conflict_merchant_public_id"] == owner["public_id"]
    assert duplicate_body["conflict_merchant_row_version"] == owner["row_version"]
    assert duplicate_body["conflict_merchant_display_name"] == "Shared Store"
    assert duplicate_body["conflict_merchant_status"] == "active"
    assert duplicate_body["conflict_merchant_deleted"] is False

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
    target = _create_catalog(client, identity.app_headers, display_name="Target")
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
        client.post(
            f"/api/merchants/catalog/{created['public_id']}/merge",
            headers=identity.app_headers,
            json={
                "expected_row_version": created["row_version"],
                "target_public_id": target["public_id"],
                "target_row_version": target["row_version"],
                "alias_policy": "none",
            },
        ),
    ]
    for response in checks:
        assert response.status_code == 403
        assert response.json()["error"] == "permission_denied"

    listed = client.get("/api/merchants/catalog", headers=identity.app_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2


def test_merchant_catalog_delete_blocks_live_config_not_historical_facts(
    client: TestClient, *, identity
) -> None:
    created = _create_catalog(client, identity.app_headers, display_name="Anchor Store")
    merchant_key = normalize_merchant("Anchor Store")
    clean_status = clean_merchant_catalog_status(" hidden ")
    assert clean_status == "hidden"
    assert clean_status in _CATALOG_WRITABLE_STATUSES
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


def test_merchant_catalog_key_changing_rename_blocks_live_config_not_historical_facts(
    client: TestClient, *, identity
) -> None:
    created = _create_catalog(
        client,
        identity.app_headers,
        display_name="Rename Source",
    )
    occupied = _create_catalog(
        client,
        identity.app_headers,
        display_name="Occupied Rename Target",
    )
    merchant_key = normalize_merchant("Rename Source")

    occupied_conflict = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "display_name": "Occupied Rename Target",
        },
    )
    assert occupied_conflict.status_code == 409
    occupied_body = occupied_conflict.json()
    assert occupied_body["error"] == "state_conflict"
    assert occupied_body["conflict_merchant_public_id"] == occupied["public_id"]
    assert occupied_body["conflict_merchant_row_version"] == occupied["row_version"]
    assert occupied_body["conflict_merchant_display_name"] == "Occupied Rename Target"
    assert occupied_body["conflict_merchant_status"] == "active"
    assert occupied_body["conflict_merchant_deleted"] is False

    _seed_enabled_alias_target(merchant_key=merchant_key)

    blocked_by_alias = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "display_name": "Rename Target",
        },
    )
    assert blocked_by_alias.status_code == 409
    assert blocked_by_alias.json()["error"] == "state_conflict"

    _disable_alias_and_seed_recurring(merchant_key=merchant_key)

    blocked_by_recurring = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "display_name": "Rename Target",
        },
    )
    assert blocked_by_recurring.status_code == 409
    assert blocked_by_recurring.json()["error"] == "state_conflict"

    _archive_recurring(merchant_key=merchant_key)
    _seed_historical_expense(merchant="Rename Source")

    renamed = client.patch(
        f"/api/merchants/catalog/{created['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": created["row_version"],
            "display_name": "Rename Target",
        },
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["display_name"] == "Rename Target"
    assert renamed.json()["merchant_key"] == normalize_merchant("Rename Target")
    assert renamed.json()["usage_count"] == 0
    _assert_historical_expense_exists(merchant="Rename Source")


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
