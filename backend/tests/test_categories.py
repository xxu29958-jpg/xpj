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

from datetime import UTC, datetime
import re

import pytest
from fastapi.testclient import TestClient

import conftest as cf
from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local
from app.services.category_service import list_category_summary
from app.services.merchant_service import display_merchant, normalize_merchant


# ── Fixtures (mirror tests/test_web_app.py setup) ───────────────────────────


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{cf.CURRENT_UPLOAD_KEY}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _save_pending(
    web_client: TestClient,
    expense_id: int,
    *,
    amount_yuan: str,
    merchant: str,
    category: str,
) -> None:
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "amount_yuan": amount_yuan,
            "merchant": merchant,
            "category": category,
            "note": "",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text


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


def test_web_categories_counts_pending_uncategorized(web_client: TestClient) -> None:
    # Two pending rows still in the default "其他" bucket.
    _create_pending(web_client)
    _create_pending(web_client)
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


def test_web_uncategorized_lists_only_uncategorized(web_client: TestClient) -> None:
    eid_other = _create_pending(web_client)  # stays "其他"
    eid_food = _create_pending(web_client)
    _save_pending(
        web_client, eid_food, amount_yuan="12.34", merchant="星巴克", category="餐饮"
    )
    resp = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert resp.status_code == 200
    ids = set(re.findall(r'name="expense_ids" value="(\d+)"', resp.text))
    assert str(eid_other) in ids
    assert str(eid_food) not in ids


def test_web_uncategorized_bulk_set_category(web_client: TestClient) -> None:
    eid = _create_pending(web_client)
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


def test_web_categories_no_secret_leak(web_client: TestClient) -> None:
    _create_pending(web_client)
    for path in ("/web/categories?ledger_id=owner", "/web/categories/uncategorized?ledger_id=owner"):
        resp = web_client.get(path)
        assert resp.status_code == 200
        body = resp.text
        assert cf.CURRENT_APP_TOKEN not in body
        assert cf.CURRENT_ADMIN_TOKEN not in body
        assert cf.CURRENT_UPLOAD_KEY not in body
        assert str(cf.BACKEND_ROOT) not in body
