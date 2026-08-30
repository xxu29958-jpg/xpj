"""Web Reference Library consumer-entry contracts.

The library is one visible Transactions-domain entry.  Existing section URLs
remain the canonical transports; the product shell, hub, and wayfinding own the
user-facing hierarchy.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CategoryPreference, CategoryRule, Expense
from app.services.category_preference_service import list_category_preferences
from app.services.time_service import now_utc


def _sidebar(body: str) -> str:
    match = re.search(r'<aside class="sidebar">.*?</aside>', body, re.S)
    assert match is not None
    return match.group(0)


def test_reference_library_is_the_single_visible_vocabulary_entry(
    web_client: TestClient,
) -> None:
    response = web_client.get("/web/library?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="transactions"' in body
    assert 'data-body-stack="product"' in body
    assert "/static/web/product/domains/transactions.css" in body

    sidebar = _sidebar(body)
    assert 'href="/web/library?ledger_id=owner"' in sidebar
    assert ">资料库<" in sidebar
    assert 'href="/web/import?ledger_id=owner"' in sidebar
    for retired_entry in (
        "/web/categories?ledger_id=owner",
        "/web/merchants?ledger_id=owner",
        "/web/tags?ledger_id=owner",
        "/web/rules?ledger_id=owner",
        "/web/recycle-bin?ledger_id=owner",
    ):
        assert f'href="{retired_entry}"' not in sidebar


def test_reference_library_hub_groups_existing_owner_surfaces(
    web_client: TestClient,
) -> None:
    response = web_client.get("/web/library?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    for group in ("交易字典", "自动化", "数据生命周期"):
        assert group in body
    for href in (
        "/web/categories?ledger_id=owner",
        "/web/merchants?ledger_id=owner",
        "/web/tags?ledger_id=owner",
        "/web/rules?ledger_id=owner",
        "/web/recycle-bin?ledger_id=owner",
    ):
        assert f'href="{href}"' in body

    assert "分类" in body
    assert "商家" in body
    assert "标签" in body
    assert "规则" in body
    assert "整个账本的已移除内容" in body


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/web/categories", "分类"),
        ("/web/merchants", "商家"),
        ("/web/tags", "标签"),
        ("/web/rules", "规则"),
        ("/web/recycle-bin", "回收站"),
    ],
)
def test_reference_library_sections_share_one_product_wayfinding(
    web_client: TestClient,
    path: str,
    heading: str,
) -> None:
    response = web_client.get(f"{path}?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="transactions"' in body
    assert 'data-body-stack="product"' in body
    assert "/static/web/product/domains/transactions.css" in body
    assert "/static/web/web.css" not in body
    assert 'href="/web/library?ledger_id=owner"' in body
    assert "资料库" in body
    assert heading in body

    sidebar = _sidebar(body)
    assert 'href="/web/library?ledger_id=owner"' in sidebar
    assert 'aria-current="page">资料库</a>' in sidebar


def test_custom_category_choice_can_be_removed_without_rewriting_history(
    web_client: TestClient,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 2600,
            "merchant": "Unicode 咖啡店",
            "category": "咖啡",
            "client_ref": "web-library-category-choice",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = created.json()["id"]

    with SessionLocal() as db:
        preference = next(
            item
            for item in list_category_preferences(db, tenant_id="owner")
            if item.name == "咖啡"
        )

    page = web_client.get("/web/categories?ledger_id=owner")
    assert page.status_code == 200
    assert "自定义分类" in page.text
    assert "咖啡" in page.text
    assert (
        f'action="/web/categories/preferences/{preference.public_id}/delete"'
        in page.text
    )
    assert f'value="{preference.row_version}"' in page.text

    deleted = web_client.post(
        f"/web/categories/preferences/{preference.public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(preference.row_version),
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"].startswith("/web/categories?")

    options = web_client.get(
        "/api/expenses/categories",
        headers=identity.app_headers,
    )
    assert options.status_code == 200
    assert "咖啡" not in options.json()["items"]
    with SessionLocal() as db:
        historical = db.scalar(select(Expense).where(Expense.id == expense_id))
        assert historical is not None
        assert historical.category == "咖啡"

    recycle = web_client.get("/web/recycle-bin?ledger_id=owner")
    assert recycle.status_code == 200
    assert "咖啡" in recycle.text
    assert "整个账本" in recycle.text


def test_stale_category_removal_keeps_the_current_owner_retryable(
    web_client: TestClient,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1800,
            "merchant": "并发测试商家",
            "category": "手作",
            "client_ref": "web-library-category-stale",
        },
    )
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        item = db.scalar(
            select(CategoryPreference).where(
                CategoryPreference.tenant_id == "owner",
                CategoryPreference.name == "手作",
            )
        )
        assert item is not None
        public_id = item.public_id
        stale_version = item.row_version
        item.row_version += 1
        fresh_version = item.row_version
        db.commit()

    response = web_client.post(
        f"/web/categories/preferences/{public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(stale_version),
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert 'data-body-stack="product"' in response.text
    assert "分类已在其它端被修改" in response.text
    assert 'role="alert"' in response.text
    assert f'data-category-key="{public_id}"' in response.text
    assert (
        f'action="/web/categories/preferences/{public_id}/delete"'
        in response.text
    )
    assert f'value="{fresh_version}"' in response.text


def test_referenced_category_removal_explains_the_required_next_step(
    web_client: TestClient,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 3200,
            "merchant": "规则引用商家",
            "category": "烘焙",
            "client_ref": "web-library-category-rule-reference",
        },
    )
    assert created.status_code == 200, created.text

    with SessionLocal() as db:
        preference = db.scalar(
            select(CategoryPreference).where(
                CategoryPreference.tenant_id == "owner",
                CategoryPreference.name == "烘焙",
            )
        )
        assert preference is not None
        now = now_utc()
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="bakery",
                category="烘焙",
                enabled=True,
                priority=10,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        public_id = preference.public_id
        row_version = preference.row_version

    response = web_client.post(
        f"/web/categories/preferences/{public_id}/delete",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(row_version),
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "仍被规则、预算或目标使用" in response.text
    assert "请先处理相关配置" in response.text
    assert f'data-category-key="{public_id}"' in response.text
    assert f'value="{row_version}"' in response.text
