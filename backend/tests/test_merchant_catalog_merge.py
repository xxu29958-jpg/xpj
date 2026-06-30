from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.merchant_service import normalize_merchant
from tests._infra.merchant_catalog import archive_recurring as _archive_recurring
from tests._infra.merchant_catalog import (
    assert_historical_expense_exists as _assert_historical_expense_exists,
)
from tests._infra.merchant_catalog import bump_catalog_row_version as _bump_catalog_row_version
from tests._infra.merchant_catalog import catalog_alias_by_key as _catalog_alias_by_key
from tests._infra.merchant_catalog import create_catalog as _create_catalog
from tests._infra.merchant_catalog import (
    disable_alias_and_seed_recurring as _disable_alias_and_seed_recurring,
)
from tests._infra.merchant_catalog import (
    seed_alias_key_conflict as _seed_alias_key_conflict,
)
from tests._infra.merchant_catalog import (
    seed_enabled_alias_target as _seed_enabled_alias_target,
)
from tests._infra.merchant_catalog import seed_historical_expense as _seed_historical_expense


def test_merchant_catalog_merge_creates_alias_and_keeps_historical_facts(
    client: TestClient, *, identity
) -> None:
    source = _create_catalog(client, identity.app_headers, display_name="Old Shop")
    target = _create_catalog(client, identity.app_headers, display_name="New Shop")
    _seed_historical_expense(merchant="Old Shop")

    merged = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "create_source_alias",
        },
    )
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["source"]["status"] == "merged"
    assert body["source"]["merged_into_public_id"] == target["public_id"]
    assert body["source"]["row_version"] == source["row_version"] + 1
    assert body["target"]["status"] == "active"
    assert body["target"]["row_version"] == target["row_version"] + 1
    assert body["created_alias_public_id"]

    alias = _catalog_alias_by_key(alias_key=normalize_merchant("Old Shop"))
    assert alias is not None
    assert alias.public_id == body["created_alias_public_id"]
    assert alias.enabled is True
    assert alias.canonical_key == normalize_merchant("New Shop")
    assert alias.alias_key == normalize_merchant("Old Shop")
    _assert_historical_expense_exists(merchant="Old Shop")

    active_only = client.get(
        "/api/merchants/catalog?include_hidden=false",
        headers=identity.app_headers,
    )
    assert [item["public_id"] for item in active_only.json()["items"]] == [
        target["public_id"]
    ]

    source_after_merge = body["source"]
    reactivate_source = client.patch(
        f"/api/merchants/catalog/{source['public_id']}",
        headers=identity.app_headers,
        json={
            "expected_row_version": source_after_merge["row_version"],
            "status": "active",
        },
    )
    assert reactivate_source.status_code == 409
    assert reactivate_source.json()["error"] == "state_conflict"

    delete_source = client.request(
        "DELETE",
        f"/api/merchants/catalog/{source['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": source_after_merge["row_version"]},
    )
    assert delete_source.status_code == 409
    assert delete_source.json()["error"] == "state_conflict"


def test_merchant_catalog_merge_none_policy_does_not_create_alias(
    client: TestClient, *, identity
) -> None:
    source = _create_catalog(client, identity.app_headers, display_name="Source None")
    target = _create_catalog(client, identity.app_headers, display_name="Target None")

    merged = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "none",
        },
    )
    assert merged.status_code == 200, merged.text
    assert merged.json()["created_alias_public_id"] is None
    assert _catalog_alias_by_key(alias_key=normalize_merchant("Source None")) is None


def test_merchant_catalog_merge_blocks_live_config_and_alias_key_conflict(
    client: TestClient, *, identity
) -> None:
    source = _create_catalog(client, identity.app_headers, display_name="Blocked Source")
    target = _create_catalog(client, identity.app_headers, display_name="Blocked Target")
    source_key = normalize_merchant("Blocked Source")
    _seed_enabled_alias_target(merchant_key=source_key)

    blocked_by_canonical_alias = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "none",
        },
    )
    assert blocked_by_canonical_alias.status_code == 409
    assert blocked_by_canonical_alias.json()["error"] == "state_conflict"

    _disable_alias_and_seed_recurring(merchant_key=source_key)

    blocked_by_recurring = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "none",
        },
    )
    assert blocked_by_recurring.status_code == 409
    assert blocked_by_recurring.json()["error"] == "state_conflict"

    _archive_recurring(merchant_key=source_key)
    _seed_alias_key_conflict(alias="Blocked Source")

    alias_conflict = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "create_source_alias",
        },
    )
    assert alias_conflict.status_code == 409
    alias_body = alias_conflict.json()
    conflict_alias = _catalog_alias_by_key(alias_key=source_key)
    assert conflict_alias is not None
    assert alias_body["error"] == "state_conflict"
    assert alias_body["conflict_alias_public_id"] == conflict_alias.public_id
    assert alias_body["conflict_alias_row_version"] == conflict_alias.row_version
    assert alias_body["conflict_alias_enabled"] is False
    assert alias_body["conflict_alias_deleted"] is False


def test_merchant_catalog_merge_rejects_invalid_state_and_rewrite_flag(
    client: TestClient, *, identity
) -> None:
    source = _create_catalog(client, identity.app_headers, display_name="Merge Source")
    target = _create_catalog(client, identity.app_headers, display_name="Merge Target")
    hidden_target = client.patch(
        f"/api/merchants/catalog/{target['public_id']}",
        headers=identity.app_headers,
        json={"expected_row_version": target["row_version"], "status": "hidden"},
    ).json()

    same = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": source["public_id"],
            "target_row_version": source["row_version"],
            "alias_policy": "none",
        },
    )
    assert same.status_code == 422
    assert same.json()["error"] == "invalid_request"

    hidden = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": hidden_target["row_version"],
            "alias_policy": "none",
        },
    )
    assert hidden.status_code == 409
    assert hidden.json()["error"] == "state_conflict"

    rewrite = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": hidden_target["row_version"],
            "alias_policy": "none",
            "rewrite_historical_expenses": True,
        },
    )
    assert rewrite.status_code == 422
    assert rewrite.json()["error"] == "invalid_request"


def test_merchant_catalog_merge_stale_tokens_return_conflict_without_partial_merge(
    client: TestClient, *, identity
) -> None:
    source = _create_catalog(client, identity.app_headers, display_name="Stale Source")
    target = _create_catalog(client, identity.app_headers, display_name="Stale Target")
    _bump_catalog_row_version(public_id=target["public_id"])

    target_stale = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": target["row_version"],
            "alias_policy": "none",
        },
    )
    assert target_stale.status_code == 409
    assert target_stale.json()["error"] == "state_conflict"

    listed = client.get("/api/merchants/catalog", headers=identity.app_headers)
    by_id = {item["public_id"]: item for item in listed.json()["items"]}
    assert by_id[source["public_id"]]["status"] == "active"
    assert by_id[source["public_id"]]["merged_into_public_id"] is None

    _bump_catalog_row_version(public_id=source["public_id"])
    source_stale = client.post(
        f"/api/merchants/catalog/{source['public_id']}/merge",
        headers=identity.app_headers,
        json={
            "expected_row_version": source["row_version"],
            "target_public_id": target["public_id"],
            "target_row_version": by_id[target["public_id"]]["row_version"],
            "alias_policy": "none",
        },
    )
    assert source_stale.status_code == 409
    assert source_stale.json()["error"] == "state_conflict"


def test_merchant_catalog_merge_is_ledger_isolated(
    client: TestClient, *, identity
) -> None:
    owner_source = _create_catalog(
        client,
        identity.app_headers,
        display_name="Owner Source",
    )
    owner_target = _create_catalog(
        client,
        identity.app_headers,
        display_name="Owner Target",
    )

    cross_source = client.post(
        f"/api/merchants/catalog/{owner_source['public_id']}/merge",
        headers=identity.gray_app_headers,
        json={
            "expected_row_version": owner_source["row_version"],
            "target_public_id": owner_target["public_id"],
            "target_row_version": owner_target["row_version"],
            "alias_policy": "none",
        },
    )
    assert cross_source.status_code == 404
    assert cross_source.json()["error"] == "not_found"
