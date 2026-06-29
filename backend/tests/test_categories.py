"""Tests for /web/categories + /web/categories/uncategorized (M3 / T10-T13).

Covers:
* normalize_merchant whitespace + case folding (no schema change).
* /web/categories renders the category dashboard with month aggregation.
* /web/categories/uncategorized lists only uncategorized pending rows.
* Bulk-set-category updates only the selected rows + flips them out of
  the uncategorized bucket.
* No secrets (token / upload_key / absolute paths) leak in the HTML.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import CategoryRule, Expense
from app.routes.web_app import _require_local as _web_require_local
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.category_service import list_category_summary
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.time_service import now_utc
from tests._infra.env import BACKEND_ROOT

# ── Fixtures (mirror tests/test_web_app.py setup) ───────────────────────────


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient, *, identity) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _save_pending(
    web_client: TestClient,
    expense_id: int,
    *,
    identity,
    amount_yuan: str,
    merchant: str,
    category: str,
) -> None:
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": amount_yuan,
            "merchant": merchant,
            "category": category,
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert resp.status_code in {303, 307}, resp.text


def _create_manual_category(
    client: TestClient,
    *,
    identity,
    category: str,
    client_ref: str,
) -> None:
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1200,
            "merchant": "分类测试",
            "category": category,
            "client_ref": client_ref,
        },
    )
    assert resp.status_code == 200, resp.text


def _category_preference(client: TestClient, *, identity, name: str) -> dict:
    resp = client.get(
        "/api/expenses/categories/preferences",
        headers=identity.app_headers,
    )
    assert resp.status_code == 200, resp.text
    return next(item for item in resp.json()["items"] if item["name"] == name)


# ── T10: merchant_service.normalize_merchant ───────────────────────────────


def test_normalize_merchant_basic() -> None:
    assert normalize_merchant("  Starbucks  ") == "starbucks"
    assert normalize_merchant("星巴克\u3000国贸店") == "星巴克 国贸店"
    assert normalize_merchant("STARBUCKS\t\t国贸店") == "starbucks 国贸店"
    assert normalize_merchant(None) == ""
    assert normalize_merchant("   ") == ""
    # Zero-width characters get scrubbed.
    assert normalize_merchant("Star\u200bbucks") == "star bucks"
    assert normalize_merchant("星巴克（自动）") == "星巴克"


def test_display_merchant_preserves_case() -> None:
    assert display_merchant("  Starbucks 国贸  ") == "Starbucks 国贸"
    assert display_merchant(None) == ""


# ── T12: /web/categories dashboard ─────────────────────────────────────────


def test_web_categories_renders_with_navigation(web_client: TestClient) -> None:
    resp = web_client.get("/web/categories?ledger_id=owner")
    assert resp.status_code == 200
    # Page heading + nav active marker.
    assert "分类账本" in resp.text
    assert 'href="/web/rules?ledger_id=owner"' in resp.text
    assert 'aria-label="选择分类月份"' in resp.text


def test_web_categories_counts_pending_uncategorized(web_client: TestClient, *, identity) -> None:
    # Two pending rows still in the default "其他" bucket.
    _create_pending(web_client, identity=identity)
    _create_pending(web_client, identity=identity)
    resp = web_client.get("/web/categories?ledger_id=owner")
    assert resp.status_code == 200
    # Both pending rows should land under the uncategorized chip.
    assert "未分类" in resp.text
    # A direct entry to the cleanup workflow is rendered.
    assert "/web/categories/uncategorized?ledger_id=owner" in resp.text


def test_category_summary_uses_stat_time_and_normalized_category_aliases(
    web_client: TestClient,
) -> None:
    with SessionLocal() as db:
        now = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
        db.add_all(
            [
                Expense(
                    tenant_id="owner",
                    amount_cents=1200,
                    merchant="补录五月",
                    category="餐饮",
                    status="confirmed",
                    expense_time=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                Expense(
                    tenant_id="owner",
                    amount_cents=800,
                    merchant="旧分类五月",
                    category="吃饭",
                    status="confirmed",
                    expense_time=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()
        dashboard = list_category_summary(db, tenant_id="owner", month="2026-05")

    food = next(item for item in dashboard.summaries if item.category == "餐饮")
    assert food.confirmed_count == 2
    assert food.confirmed_amount_cents == 2000


# ── T13: /web/categories/uncategorized ─────────────────────────────────────


def test_category_summary_uses_accounting_timezone_month_bounds(
    web_client: TestClient,
) -> None:
    del web_client
    with SessionLocal() as db:
        now = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=990,
                merchant="Boundary Cafe",
                category="Boundary",
                status="confirmed",
                expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
                confirmed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        shanghai = list_category_summary(
            db,
            tenant_id="owner",
            month="2026-05",
            timezone_name="Asia/Shanghai",
        )
        utc = list_category_summary(
            db,
            tenant_id="owner",
            month="2026-05",
            timezone_name="UTC",
        )

    assert any(item.category == "Boundary" for item in shanghai.summaries)
    assert all(item.category != "Boundary" for item in utc.summaries)


def test_custom_category_preference_delete_restore_controls_options(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="咖啡", client_ref="cat-pref-coffee"
    )
    preference = _category_preference(client, identity=identity, name="咖啡")
    assert preference["usage_count"] == 1
    categories = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert "咖啡" in categories.json()["items"]

    deleted = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers,
        json={"expected_row_version": preference["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    hidden = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert "咖啡" not in hidden.json()["items"]

    recycle = client.get("/api/recycle-bin", headers=identity.app_headers)
    assert recycle.status_code == 200
    assert any(
        item["kind"] == "category_preference" and item["title"] == "咖啡"
        for item in recycle.json()["items"]
    )

    restored = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": deleted.json()["row_version"]},
    )
    assert restored.status_code == 200, restored.text
    visible = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert "咖啡" in visible.json()["items"]


def test_deleted_preference_suppresses_historical_fallback_only_for_that_key(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="咖啡", client_ref="cat-pref-hide"
    )
    preference = _category_preference(client, identity=identity, name="咖啡")
    deleted = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers,
        json={"expected_row_version": preference["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    with SessionLocal() as db:
        now = now_utc()
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=900,
                merchant="历史手作",
                category="手作",
                status="confirmed",
                expense_time=now,
                confirmed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    categories = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert categories.status_code == 200
    assert "咖啡" not in categories.json()["items"]
    assert "手作" in categories.json()["items"]


def test_default_category_usage_does_not_create_custom_preference(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="吃饭", client_ref="cat-pref-default"
    )
    resp = client.get(
        "/api/expenses/categories/preferences",
        headers=identity.app_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_delete_category_preference_rejects_active_rule_reference(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="咖啡", client_ref="cat-pref-rule"
    )
    preference = _category_preference(client, identity=identity, name="咖啡")
    with SessionLocal() as db:
        now = now_utc()
        ensure_category_preference_for_name(db, tenant_id="owner", name="咖啡")
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="coffee",
                category="咖啡",
                enabled=True,
                priority=10,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    deleted = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers,
        json={"expected_row_version": preference["row_version"]},
    )
    assert deleted.status_code == 409
    assert deleted.json()["error"] == "state_conflict"


def test_web_uncategorized_lists_only_uncategorized(web_client: TestClient, *, identity) -> None:
    eid_other = _create_pending(web_client, identity=identity)  # stays "其他"
    eid_food = _create_pending(web_client, identity=identity)
    _save_pending(
        web_client, eid_food, identity=identity,
        amount_yuan="12.34", merchant="星巴克", category="餐饮",
    )
    resp = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert resp.status_code == 200
    ids = set(re.findall(r'name="expense_ids" value="(\d+)"', resp.text))
    assert str(eid_other) in ids
    assert str(eid_food) not in ids


def test_web_uncategorized_bulk_set_category(web_client: TestClient, *, identity) -> None:
    eid = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        "/web/categories/uncategorized/bulk-set",
        data={
            "ledger_id": "owner",
            "expense_ids": [str(eid)],
            "category": "餐饮",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    follow = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert follow.status_code == 200
    ids = set(re.findall(r'name="expense_ids" value="(\d+)"', follow.text))
    # Row flipped out of the uncategorized bucket.
    assert str(eid) not in ids


def test_web_uncategorized_bulk_requires_selection(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/categories/uncategorized/bulk-set",
        data={"ledger_id": "owner", "category": "餐饮"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    loc = resp.headers.get("location", "")
    assert "/web/categories/uncategorized" in loc and "msg=" in loc


# ── Loopback gate + secret-leak guard ─────────────────────────────────────


def test_web_categories_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/categories").status_code == 403
    assert client.get("/web/categories/uncategorized").status_code == 403


def test_web_categories_no_secret_leak(web_client: TestClient, *, identity) -> None:
    _create_pending(web_client, identity=identity)
    for path in ("/web/categories?ledger_id=owner", "/web/categories/uncategorized?ledger_id=owner"):
        resp = web_client.get(path)
        assert resp.status_code == 200
        body = resp.text
        assert identity.app_token not in body
        assert identity.admin_token not in body
        assert identity.upload_key not in body
        assert str(BACKEND_ROOT) not in body
