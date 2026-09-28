"""Web Reference Library consumer-entry contracts.

The library is one visible Transactions-domain entry.  Existing section URLs
remain the canonical transports; the product shell, hub, and wayfinding own the
user-facing hierarchy.
"""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CategoryPreference, CategoryRule, Expense, Ledger, LedgerMember, Tag
from app.services.category_preference_service import list_category_preferences
from app.services.saved_view_service import create_view
from app.services.time_service import now_utc
from tests._web_native_form_support import hidden_post_forms


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
    for group in ("常用查询", "交易字典", "自动化", "数据生命周期"):
        assert group in body
    for href in (
        "/web/saved-views?ledger_id=owner",
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


def test_reference_library_counts_views_without_resolving_each_tag(web_client: TestClient, monkeypatch) -> None:
    with SessionLocal() as db:
        owner_id = db.scalar(select(Ledger.owner_account_id).where(Ledger.ledger_id == "owner"))
        tag = Tag(tenant_id="owner", name="旅行", key="旅行")
        other_id = "library_saved_view_other"
        db.add(Ledger(ledger_id=other_id, name="另一本账本", owner_account_id=owner_id))
        db.flush()
        db.add_all([tag, LedgerMember(ledger_id=other_id, account_id=owner_id, role="owner")])
        db.commit()
        definition = {"month_mode": "current", "month": None, "filter": "", "home_currency_code": "CNY"}
        for tenant_id, name, tag_id in (
            ("owner", "旅行查询", tag.public_id), ("owner", "无标签查询", None),
            (other_id, "另一本查询", None),
        ):
            create_view(db, tenant_id=tenant_id, actor_account_id=owner_id,
                        idempotency_key=str(uuid4()), name=name, tag_public_id=tag_id, **definition)
        tag.deleted_at = now_utc()
        db.commit()

    def reject_resolution(*args, **kwargs):
        del args, kwargs
        pytest.fail("Library count must not resolve saved-view details or tags")

    monkeypatch.setattr("app.services.saved_view_service._detail", reject_resolution)
    monkeypatch.setattr("app.services.saved_view_service._tag", reject_resolution)
    response = web_client.get("/web/library?ledger_id=owner")

    assert response.status_code == 200
    assert "2 个共享视图" in response.text
    assert 'href="/web/saved-views?ledger_id=owner"' in response.text


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/web/saved-views", "保存的视图"),
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
            "home_currency_code": "CNY", "amount_cents": 2600,
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
    assert f'data-restore-key="category_preference:{preference.public_id}"' in recycle.text


def test_stale_category_removal_keeps_the_current_owner_retryable(
    web_client: TestClient,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "home_currency_code": "CNY", "amount_cents": 1800,
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
            "home_currency_code": "CNY", "amount_cents": 3200,
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
        rule = CategoryRule(
            tenant_id="owner",
            keyword="bakery",
            category="烘焙",
            enabled=True,
            priority=10,
            created_at=now,
            updated_at=now,
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id
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

    # A rejection must lead to the actual blocking object, not leave the user
    # searching every rule and plan. Resolve it through the shipped editor.
    editor_links = [unescape(href) for href in re.findall(r'href="([^"]+)"', response.text)
        if unescape(href).startswith(f"/web/rules/{rule_id}/edit?ledger_id=owner")]
    assert len(editor_links) == 1
    editor_url = editor_links[0]
    editor = web_client.get(editor_url)
    assert editor.status_code == 200, editor.text
    assert 'value="bakery"' in editor.text
    edit_action = f"/web/rules/{rule_id}/edit"
    original_form = hidden_post_forms(editor.text)[edit_action]
    changed = web_client.post(edit_action, data={**original_form,
        "keyword": "bakery", "category": "餐饮", "priority": "10"}, follow_redirects=False)
    assert changed.status_code in (302, 303), changed.text

    return_url = urlsplit(changed.headers["location"])
    assert return_url.path == "/web/categories"
    assert parse_qs(return_url.query)["ledger_id"] == ["owner"]
    assert return_url.fragment == f"category-{public_id}"
    returned = web_client.get(changed.headers["location"])
    assert f'id="category-{public_id}"' in returned.text
    remove_action = f"/web/categories/preferences/{public_id}/delete"
    current_form = hidden_post_forms(returned.text)[remove_action]
    removed = web_client.post(remove_action, data=current_form, follow_redirects=False)
    assert removed.status_code in (302, 303), removed.text
    with SessionLocal() as db:
        original_expense = db.scalar(select(Expense).where(Expense.public_id == created.json()["public_id"]))
        assert original_expense.category == "烘焙"
        assert original_expense.amount_cents == 3200
        assert db.scalar(select(CategoryRule).where(CategoryRule.id == rule_id)).category == "餐饮"
        preference = db.scalar(select(CategoryPreference).where(CategoryPreference.public_id == public_id))
        assert preference.deleted_at is not None


@pytest.mark.parametrize("source", ["budget", "goal"])
def test_category_plan_reference_opens_the_saved_editor_and_returns_to_removal(
    web_client: TestClient, identity, source: str,
) -> None:
    created = web_client.post("/api/expenses/manual", headers=identity.app_headers,
        json={"home_currency_code": "CNY", "amount_cents": 3200, "merchant": "计划引用商家",
            "category": "烘焙", "client_ref": f"web-category-plan-reference-{source}"})
    assert created.status_code == 200, created.text
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    goal_name = '烘焙 <img src=x onerror="alert(1)">'
    if source == "budget":
        saved = web_client.put("/api/budgets/monthly/2026-10", headers=headers,
            json={"home_currency_code": "CNY", "expected_row_version": None, "total_amount_cents": 50000,
                "excluded_categories": ["烘焙"], "category_budgets": [{"category": "烘焙", "amount_cents": 5000}]})
        assert saved.status_code == 200, saved.text
        editor_url = "/web/budgets?ledger_id=owner&month=2026-10"
        edit_action = "/web/budgets/save"
        read_url = "/api/budgets/monthly?month=2026-10"
    else:
        saved = web_client.post("/api/goals", headers=headers,
            json={"home_currency_code": "CNY", "name": goal_name, "month": "2026-10",
                "category": "烘焙", "target_amount_cents": 5000})
        assert saved.status_code == 201, saved.text
        goal_id = saved.json()["public_id"]
        edit_action = f"/web/goals/{goal_id}/edit"
        editor_url = f"{edit_action}?ledger_id=owner"
        read_url = f"/api/goals/{goal_id}"
    original_plan = web_client.get(read_url, headers=identity.app_headers).json()
    categories = web_client.get("/web/categories?ledger_id=owner")
    form_action = next(action for action in hidden_post_forms(categories.text)
        if action.startswith("/web/categories/preferences/"))
    form = hidden_post_forms(categories.text)[form_action]
    rejected = web_client.post(form_action, data=form, follow_redirects=False)
    assert rejected.status_code == 422, rejected.text
    editor_links = [unescape(href) for href in re.findall(r'href="([^"]+)"', rejected.text)
        if unescape(href).startswith(editor_url)]
    assert len(editor_links) == 1
    editor_url = editor_links[0]
    assert web_client.get(read_url, headers=identity.app_headers).json() == original_plan
    if source == "goal":
        assert goal_name in unescape(rejected.text)
        assert "烘焙 &lt;img" in rejected.text
        assert '<img src=x onerror="alert(1)">' not in rejected.text
    editor = web_client.get(editor_url)
    assert editor.status_code == 200, editor.text
    original_form = hidden_post_forms(editor.text)[edit_action]
    assert 'name="month" value="2026-10"' in editor.text
    if source == "budget":
        changes = {"total_amount_yuan": "500.00", "rollover_amount_yuan": "0.00",
            "non_monthly_amount_yuan": "0.00", "excluded_categories": "",
            "category_budget_category": ["烘焙"], "category_budget_amount_yuan": ["50.00"],
            "category_budget_remove": ["0"]}
    else:
        changes = {"name": goal_name, "month": "2026-10", "category": "餐饮", "target_amount_yuan": "50.00"}
    changed = web_client.post(edit_action, data={**original_form, **changes}, follow_redirects=False)
    assert changed.status_code in (302, 303), changed.text
    changed_plan = web_client.get(read_url, headers=identity.app_headers).json()
    if source == "budget":
        assert changed_plan["total_amount_cents"] == 50000
        assert changed_plan["excluded_categories"] == []
        assert changed_plan["category_budgets"] == []
    else:
        assert changed_plan["category"] == "餐饮"
        assert changed_plan["target_amount_cents"] == 5000
    preference_id = form_action.split("/")[-2]
    return_url = urlsplit(changed.headers["location"])
    assert return_url.path == "/web/categories"
    assert parse_qs(return_url.query)["ledger_id"] == ["owner"]
    assert return_url.fragment == f"category-{preference_id}"
    returned = web_client.get(changed.headers["location"])
    assert f'id="category-{preference_id}"' in returned.text
    removed = web_client.post(form_action, data=hidden_post_forms(returned.text)[form_action], follow_redirects=False)
    assert removed.status_code in (302, 303), removed.text
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.public_id == created.json()["public_id"]))
        assert expense.category == "烘焙"
        assert expense.amount_cents == 3200
        preference_id = form_action.split("/")[-2]
        preference = db.scalar(select(CategoryPreference).where(CategoryPreference.public_id == preference_id))
        assert preference.deleted_at is not None
