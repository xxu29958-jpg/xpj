"""v0.7 merchant alias contract: ledger isolation, conflicts, and writer guard."""

from __future__ import annotations

from datetime import UTC, datetime

from api_contract_helpers import patch_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.services.merchant_alias_service import resolve_canonical_merchant
from tests._infra.assets import PNG_BYTES


def _create_alias(
    client: TestClient,
    headers: dict[str, str],
    *,
    canonical: str = "星巴克",
    alias: str = "STARBUCKS 国贸店",
    enabled: bool = True,
) -> dict:
    response = client.post(
        "/api/merchants/aliases",
        headers=headers,
        json={
            "canonical_merchant": canonical,
            "alias": alias,
            "enabled": enabled,
        },
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


def _upload_pending(client: TestClient, *, identity, merchant: str, category: str = "其他") -> int:
    uploaded = client.post(
        identity.upload_url_path,
        headers={"Content-Type": "image/png"},
        content=PNG_BYTES,
    )
    assert uploaded.status_code == 200, uploaded.text
    expense_id = int(uploaded.json()["id"])
    patched = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 3800,
            "merchant": merchant,
            "category": category,
        },
    )
    assert patched.status_code == 200, patched.text
    return expense_id


def test_merchant_alias_crud_and_conflict_within_ledger(client: TestClient, *, identity) -> None:
    created = _create_alias(client, identity.app_headers)
    assert created["canonical_merchant"] == "星巴克"
    assert created["canonical_key"] == "星巴克"
    assert created["alias"] == "STARBUCKS 国贸店"
    assert created["alias_key"] == "starbucks 国贸店"
    public_id = created["public_id"]

    listed = client.get("/api/merchants/aliases", headers=identity.app_headers)
    assert listed.status_code == 200
    assert [item["public_id"] for item in listed.json()["items"]] == [public_id]

    conflict = client.post(
        "/api/merchants/aliases",
        headers=identity.app_headers,
        json={"canonical_merchant": "另一家", "alias": "starbucks 国贸店"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "merchant_alias_conflict"

    same_as_canonical = client.post(
        "/api/merchants/aliases",
        headers=identity.app_headers,
        json={"canonical_merchant": "罗森", "alias": " 罗森 "},
    )
    assert same_as_canonical.status_code == 422
    assert same_as_canonical.json()["error"] == "invalid_request"

    updated = client.patch(
        f"/api/merchants/aliases/{public_id}",
        headers=identity.app_headers,
        json={
            "expected_updated_at": created["updated_at"],
            "canonical_merchant": "星巴克咖啡",
            "alias": "STARBUCKS 北京店",
            "enabled": False,
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["canonical_key"] == "星巴克咖啡"
    assert payload["alias_key"] == "starbucks 北京店"
    assert payload["enabled"] is False

    deleted = client.request(
        "DELETE",
        f"/api/merchants/aliases/{public_id}",
        headers=identity.app_headers,
        json={"expected_updated_at": payload["updated_at"]},
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "ok"}
    assert (
        client.get("/api/merchants/aliases", headers=identity.app_headers).json()["items"]
        == []
    )


def test_merchant_aliases_are_ledger_isolated(client: TestClient, *, identity) -> None:
    owner = _create_alias(
        client,
        identity.app_headers,
        canonical="星巴克",
        alias="共同别名",
    )
    tester = _create_alias(
        client,
        identity.gray_app_headers,
        canonical="测试商家",
        alias="共同别名",
    )

    owner_items = client.get("/api/merchants/aliases", headers=identity.app_headers).json()[
        "items"
    ]
    tester_items = client.get(
        "/api/merchants/aliases", headers=identity.gray_app_headers
    ).json()["items"]
    assert [item["public_id"] for item in owner_items] == [owner["public_id"]]
    assert [item["public_id"] for item in tester_items] == [tester["public_id"]]
    assert owner_items[0]["canonical_merchant"] == "星巴克"
    assert tester_items[0]["canonical_merchant"] == "测试商家"

    cross_patch = client.patch(
        f"/api/merchants/aliases/{owner['public_id']}",
        headers=identity.gray_app_headers,
        json={
            "expected_updated_at": owner["updated_at"],
            "canonical_merchant": "越权改名",
        },
    )
    assert cross_patch.status_code == 404
    assert cross_patch.json()["error"] == "merchant_alias_not_found"


def test_viewer_cannot_mutate_merchant_aliases(client: TestClient, *, identity) -> None:
    created = _create_alias(client, identity.app_headers)
    _demote_owner_ledger_to_viewer()

    checks = [
        client.post(
            "/api/merchants/aliases",
            headers=identity.app_headers,
            json={"canonical_merchant": "KFC", "alias": "肯德基"},
        ),
        client.patch(
            f"/api/merchants/aliases/{created['public_id']}",
            headers=identity.app_headers,
            json={
                "expected_updated_at": created["updated_at"],
                "enabled": False,
            },
        ),
        client.request(
            "DELETE",
            f"/api/merchants/aliases/{created['public_id']}",
            headers=identity.app_headers,
            json={"expected_updated_at": created["updated_at"]},
        ),
    ]
    for response in checks:
        assert response.status_code == 403
        assert response.json()["error"] == "permission_denied"

    listed = client.get("/api/merchants/aliases", headers=identity.app_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_resolve_canonical_merchant_uses_enabled_alias_only(client: TestClient, *, identity) -> None:
    _create_alias(client, identity.app_headers, canonical="星巴克", alias="STARBUCKS 国贸店")
    _create_alias(
        client,
        identity.app_headers,
        canonical="肯德基",
        alias="KFC 国贸店",
        enabled=False,
    )

    with SessionLocal() as db:
        assert (
            resolve_canonical_merchant(db, tenant_id="owner", merchant=" starbucks 国贸店 ")
            == "星巴克"
        )
        assert (
            resolve_canonical_merchant(db, tenant_id="owner", merchant="KFC 国贸店")
            == "KFC 国贸店"
        )
        assert (
            resolve_canonical_merchant(
                db,
                tenant_id="tester_1",
                merchant="STARBUCKS 国贸店",
            )
            == "STARBUCKS 国贸店"
        )


def test_rules_preview_and_apply_use_enabled_merchant_alias(client: TestClient, *, identity) -> None:
    expense_id = _upload_pending(client, merchant="STARBUCKS 国贸店", identity=identity)
    _create_alias(client, identity.app_headers, canonical="星巴克", alias="STARBUCKS 国贸店")

    rule = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "星巴克", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert rule.status_code == 200, rule.text

    preview = client.post(
        "/api/rules/preview",
        headers=identity.app_headers,
        json={
            "keyword": "星巴克",
            "target_category": "餐饮",
            "match_field": "merchant",
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["matched_count"] == 1
    assert payload["items"][0]["id"] == expense_id
    assert payload["items"][0]["current_category"] == "其他"

    bulk_preview = client.post("/api/rules/apply-pending/preview", headers=identity.app_headers)
    assert bulk_preview.status_code == 200, bulk_preview.text
    apply = client.post(
        "/api/rules/apply-pending",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": bulk_preview.json()["preview_token"]},
    )
    assert apply.status_code == 200, apply.text
    assert apply.json()["changed_count"] == 1

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    item = next(row for row in pending.json() if row["id"] == expense_id)
    assert item["merchant"] == "STARBUCKS 国贸店"
    assert item["category"] == "餐饮"


def test_lifestyle_stats_collapses_frequent_merchants_with_alias(client: TestClient, *, identity) -> None:
    _create_alias(client, identity.app_headers, canonical="Starbucks", alias="SBUX")
    now = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        db.add_all(
            [
                Expense(
                    tenant_id="owner",
                    amount_cents=1200,
                    merchant="SBUX",
                    category="Coffee",
                    status="confirmed",
                    expense_time=now,
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                Expense(
                    tenant_id="owner",
                    amount_cents=1800,
                    merchant="Starbucks",
                    category="Coffee",
                    status="confirmed",
                    expense_time=now,
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()

    response = client.get(
        "/api/stats/lifestyle?month=2026-05&timezone=UTC",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    assert {"merchant": "Starbucks", "count": 2} in response.json()["frequent_merchants"]
    assert all(item["merchant"] != "SBUX" for item in response.json()["frequent_merchants"])


def test_disabled_merchant_alias_does_not_affect_rules(client: TestClient, *, identity) -> None:
    _upload_pending(client, merchant="KFC 国贸店", identity=identity)
    _create_alias(
        client,
        identity.app_headers,
        canonical="肯德基",
        alias="KFC 国贸店",
        enabled=False,
    )

    preview = client.post(
        "/api/rules/preview",
        headers=identity.app_headers,
        json={"keyword": "肯德基", "target_category": "餐饮", "match_field": "merchant"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["matched_count"] == 0
