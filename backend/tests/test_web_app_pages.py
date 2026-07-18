"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.version import STATIC_ASSET_VERSION


def _assert_in_order(text: str, labels: list[str]) -> None:
    cursor = -1
    for label in labels:
        cursor = text.find(label, cursor + 1)
        assert cursor >= 0, label


def _save_expense_detail_and_assert_return_context(
    web_client: TestClient,
    *,
    expense_id: int,
    response_text: str,
) -> None:
    row_version = re.search(
        r'name="expected_row_version" value="([^"]+)"',
        response_text,
    )
    assert row_version is not None
    saved = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": row_version.group(1),
            "amount_yuan": "12.34",
            "original_currency": "CNY",
            "merchant": "层级测试商家",
            "category": "其他",
            "tags": "",
            "note": "",
            "return_to": "confirmed",
            "return_month": "2026-07",
            "return_page": "3",
            "return_tag": "旅行",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/web/confirmed?ledger_id=owner&month=2026-07&page=3&tag=%E6%97%85%E8%A1%8C"


def test_web_pending_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    assert '<h1 class="page-title" id="pending-title">待我处理</h1>' in resp.text


def test_web_pending_empty_states_offer_product_next_steps(web_client: TestClient) -> None:
    """完整队列为空时回到流水；筛选无结果时回到完整收件队列。

    普通产品页不得把用户带进本机 Owner Console 或技术配置流程。
    """
    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    assert "收件队列已经清空" in body
    assert 'href="/web/confirmed?ledger_id=owner"' in body
    assert 'href="/owner/upload-links"' not in body

    # 过滤态为空时回到完整收件队列，不伪装成「没有任何账单」。
    filtered = web_client.get("/web/pending?ledger_id=owner&filter=duplicate")
    assert filtered.status_code == 200
    assert "没有符合当前条件的账单" in filtered.text
    assert 'href="/web/pending?ledger_id=owner"' in filtered.text


def test_web_confirmed_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed")
    assert resp.status_code == 200
    assert '<h1 class="page-title" id="confirmed-title">全部流水</h1>' in resp.text
    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in resp.text
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in resp.text
    assert f"/static/shared/tokens.css?v={STATIC_ASSET_VERSION}" in resp.text
    assert 'data-page="transactions" data-page-level="primary"' in resp.text


def test_web_mobile_primary_nav_contract(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    primary = re.search(r'<nav class="mobile-primary-nav".*?</nav>', body, re.S)
    assert primary is not None
    assert all(label in primary.group(0) for label in ["收件", "流水", "往来", "计划", "洞察"])
    assert "首页" not in primary.group(0)
    assert "更多" not in primary.group(0)
    assert re.search(
        r'href="/web/confirmed\?ledger_id=owner"[^>]+aria-current="location"',
        primary.group(0),
    )
    assert 'id="ledger-switcher-trigger" type="button"' in body
    assert 'aria-controls="ledger-popover" aria-expanded="false"' in body
    assert "私人账本" in body
    assert "家庭账本</div>" not in body

    desktop = re.search(r'<nav class="desktop-nav" aria-label="产品导航">.*?</nav>', body, re.S)
    assert desktop is not None
    desktop_nav = re.sub(r"\{#.*?#\}", "", desktop.group(0), flags=re.S)
    assert "账单流" not in desktop_nav
    assert re.search(
        r'href="/web/confirmed\?ledger_id=owner"[^>]+aria-current="location"',
        desktop_nav,
    )
    _assert_in_order(
        desktop_nav,
        [
            "收件",
            "流水",
            "往来",
            "计划",
            "洞察",
            "全部流水",
            "搜索",
            "资料库",
            "导入导出",
            "工作区",
        ],
    )

    reports = web_client.get("/web/reports?ledger_id=owner")
    assert reports.status_code == 200
    reports_desktop = re.search(
        r'<nav class="desktop-nav" aria-label="产品导航">.*?</nav>',
        reports.text,
        re.S,
    )
    assert reports_desktop is not None
    assert 'class="nav-item active" href="/web/overview?ledger_id=owner"' in reports_desktop.group(0)
    assert 'class="active" href="/web/reports?ledger_id=owner"' in reports_desktop.group(0)

    plan = web_client.get("/web/goals?ledger_id=owner")
    assert plan.status_code == 200
    plan_desktop = re.search(
        r'<nav class="desktop-nav" aria-label="产品导航">.*?</nav>',
        plan.text,
        re.S,
    )
    assert plan_desktop is not None
    assert 'class="nav-subnav" aria-label="当前领域页面"' in plan_desktop.group(0)
    assert re.search(
        r'class="active" href="/web/goals\?ledger_id=owner"[^>]+aria-current="page"',
        plan_desktop.group(0),
    )


def test_web_secondary_page_uses_domain_subnav(
    web_client: TestClient,
) -> None:
    resp = web_client.get("/web/search?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    subnav = re.search(r'<nav class="mobile-plan-nav".*?</nav>', body, re.S)
    assert subnav is not None
    assert 'data-page="transactions" data-page-level="secondary"' in body
    assert re.search(
        r'class="active" href="/web/search\?ledger_id=owner"[^>]+aria-current="page"',
        subnav.group(0),
    )


def test_web_deep_pages_declare_tertiary_product_level(
    web_client: TestClient,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "层级测试商家",
            "category": "其他",
            "expense_time": "2026-07-17T04:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])
    response = web_client.get(
        f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=confirmed"
        "&return_month=2026-07&return_page=3&return_tag=旅行"
    )

    assert response.status_code == 200
    assert 'data-page="expense-detail" data-page-level="tertiary"' in response.text
    assert 'class="page-back-link"' in response.text
    assert "账单详情" in response.text
    assert "返回账本" in response.text
    assert "/web/confirmed?ledger_id=owner&amp;month=2026-07&amp;page=3&amp;tag=%E6%97%85%E8%A1%8C" in response.text
    assert 'name="return_to" value="confirmed"' in response.text
    assert 'name="return_month" value="2026-07"' in response.text
    assert 'name="return_page" value="3"' in response.text
    assert 'name="return_tag" value="旅行"' in response.text
    assert re.search(
        r'class="nav-item active" href="/web/confirmed\?ledger_id=owner"'
        r'[^>]+aria-current="location"',
        response.text,
    )
    assert 'class="expense-lines-scroll"' in response.text
    assert 'aria-label="小票明细，可横向滚动"' in response.text
    assert 'aria-label="家庭拆账明细，可横向滚动"' in response.text
    field_names = (
        "明细类型",
        "明细名称",
        "明细数量",
        "明细单价",
        "明细金额",
        "明细分类",
        "拆账成员",
        "拆账金额",
        "拆账备注",
    )
    expected_accessible_names = {
        f"第 {row_index} 行{field_name}" for row_index in range(1, 4) for field_name in field_names
    }
    for accessible_name in expected_accessible_names:
        labels = re.findall(
            rf'aria-label="{re.escape(accessible_name)}(?:（[^"]+）)?"',
            response.text,
        )
        assert len(labels) == 1

    _save_expense_detail_and_assert_return_context(
        web_client,
        expense_id=expense_id,
        response_text=response.text,
    )

    css = web_client.get("/static/web/product/detail.css")
    assert css.status_code == 200
    assert ".expense-lines-table" in css.text
    assert "min-width: calc(var(--space-12) * 9)" in css.text
    assert "overflow-x: auto" in css.text

    category_detail = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert category_detail.status_code == 200
    assert 'data-page="category-detail" data-page-level="tertiary"' in category_detail.text


def test_web_month_picker_links_drop_page_param(web_client: TestClient) -> None:
    """Switching month must land on page 1: carrying ``page=2`` into a month
    with a single page rendered the false「该月还没有已确认账单」empty state
    (with the pager gone, leaving no recovery control)."""
    resp = web_client.get("/web/confirmed?ledger_id=owner&month=2026-05&page=2")
    assert resp.status_code == 200
    hrefs = re.findall(r'href="([^"]*month=2026-0[46][^"]*)"', resp.text)
    assert any("month=2026-04" in h for h in hrefs), hrefs
    assert any("month=2026-06" in h for h in hrefs), hrefs
    assert all("page=" not in h for h in hrefs), hrefs
    # Other filters survive the month switch.
    assert all("ledger_id=owner" in h for h in hrefs), hrefs


def test_web_reports_local_returns_200(web_client: TestClient) -> None:
    # UI/UX 批 14: /web/stats 整页归并进 /web/reports(月度统计页删除)。
    resp = web_client.get("/web/reports?month=2026-05")
    assert resp.status_code == 200
    assert '<h1 class="page-title">分析</h1>' in resp.text
    assert "动态报表，六个月看清节奏。" not in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/web/reports?month=2026-13",
        "/web/confirmed?month=0000-05",
        "/web/categories?month=2026-5",
    ],
)
def test_web_month_pages_reject_invalid_month_labels(web_client: TestClient, path: str) -> None:
    resp = web_client.get(path)
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


def test_web_search_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/search?ledger_id=owner")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text


def test_web_domain_secondary_pages_remain_reachable(web_client: TestClient) -> None:
    """Each capability is reachable from its owning domain, not a catch-all home."""
    inbox = web_client.get("/web/pending?ledger_id=owner")
    assert inbox.status_code == 200
    assert 'href="/web/tasks?ledger_id=owner"' in inbox.text

    plan = web_client.get("/web/budgets?ledger_id=owner")
    assert plan.status_code == 200
    assert 'href="/web/income-plans?ledger_id=owner"' in plan.text
    assert 'href="/web/budget-advise?ledger_id=owner"' in plan.text
    assert 'class="product-shell has-domain-subnav"' in plan.text

    overview = web_client.get("/web/overview?ledger_id=owner")
    assert overview.status_code == 200
    assert 'href="/web/dashboard/cards?ledger_id=owner"' in overview.text

    library = web_client.get("/web/library?ledger_id=owner")
    assert library.status_code == 200
    for path in ("categories", "merchants", "tags", "rules"):
        assert f'href="/web/{path}?ledger_id=owner"' in library.text

    product_css = web_client.get("/static/web/product/shell.css")
    assert ".product-shell.has-domain-subnav .product-topbar" in product_css.text
    assert "top: var(--space-9)" in product_css.text
    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in product_css.text
    assert "inset-block-end: 0" in product_css.text

    tasks = web_client.get("/web/tasks?ledger_id=owner")
    assert tasks.status_code == 200
    assert "后端重启" not in tasks.text
    assert "任务不跨重启" not in tasks.text
