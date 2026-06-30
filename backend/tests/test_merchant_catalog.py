"""ADR-0053 merchant catalog backend contract."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember, MerchantAlias, MerchantCatalog, RecurringItem
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


def _bump_catalog_row_version(*, public_id: str) -> None:
    with SessionLocal() as db:
        item = db.scalar(
            select(MerchantCatalog)
            .where(MerchantCatalog.tenant_id == "owner")
            .where(MerchantCatalog.public_id == public_id)
            .limit(1)
        )
        assert item is not None
        item.row_version += 1
        item.updated_at = now_utc()
        db.commit()


def _catalog_alias_by_key(*, alias_key: str) -> MerchantAlias | None:
    with SessionLocal() as db:
        return db.scalar(
            select(MerchantAlias)
            .where(MerchantAlias.tenant_id == "owner")
            .where(MerchantAlias.alias_key == alias_key)
            .limit(1)
        )


def _seed_alias_key_conflict(*, alias: str) -> None:
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            MerchantAlias(
                tenant_id="owner",
                canonical_merchant="Other Store",
                canonical_key=normalize_merchant("Other Store"),
                alias=alias,
                alias_key=normalize_merchant(alias),
                enabled=False,
                created_at=now,
                updated_at=now,
            )
        )
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


def test_merchant_catalog_key_changing_rename_blocks_live_config_not_historical_facts(
    client: TestClient, *, identity
) -> None:
    created = _create_catalog(
        client,
        identity.app_headers,
        display_name="Rename Source",
    )
    merchant_key = normalize_merchant("Rename Source")
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

    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.merchant == "Rename Source")
            .limit(1)
        )
        assert expense is not None


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

    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.merchant == "Old Shop")
            .limit(1)
        )
        assert expense is not None

    active_only = client.get(
        "/api/merchants/catalog?include_hidden=false",
        headers=identity.app_headers,
    )
    assert [item["public_id"] for item in active_only.json()["items"]] == [
        target["public_id"]
    ]


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
    assert alias_conflict.json()["error"] == "state_conflict"


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
