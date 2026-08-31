"""Product-shell contracts for the Web UI/IA rebuild (218-D S3, 移植自产品矿并适配 main).

S3 落「壳基座」: base.html / _sidebar_nav.html 重写 + product 设计系统 CSS
+ web_common 展示 helper。S4 落「收件域正文」: pending/duplicates 两页
换 product 新标记, 经 _product_body_domains 开关断旧栈、挂 domains/inbox.css,
/web 根 303→/web/pending —— 页面级断言族在 test_web_inbox_rebuild.py,
本文件只钉壳层与旧栈分流防回归。

218-D S3-R1 翻转 (#256 P1: 收件行整列塌缩): 挂载策略按页面正文标记新旧分流——
- 正文仍是旧标记的页 (debts/budgets 等): 旧全局栈+页级 CSS 保持在场
  (本文件钉死防回归), 对应 domain 模块不双挂 (矿域模块与旧页共享类名谱系
  .exp-row/.timeline-row 等, 双挂则旧规则被盖、新 grid 不认嵌套标记)。
- 正文已是新标记的页 (overview S2; 收件域两页 S4): 断旧栈, 挂对应 domain 模块。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.version import STATIC_ASSET_VERSION

_RETIRED_GLOBAL_STACK = (
    "/static/web/web.css",
    "/static/web/_base.css",
    "/static/web/_shell.css",
    "/static/web/_misc.css",
    "/static/web/components/",
)


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def _assert_shell_chrome_has_no_inline_style(body: str) -> None:
    """壳 chrome (侧边导航 + 顶栏) 零内联样式。"""
    sidebar = re.search(r'<aside class="sidebar">.*?</aside>', body, re.S)
    assert sidebar is not None
    assert 'style="' not in sidebar.group(0)
    topbar = re.search(r'<header class="product-topbar">.*?</header>', body, re.S)
    assert topbar is not None
    assert 'style="' not in topbar.group(0)


@pytest.mark.parametrize(
    ("path", "domain", "primary_href", "page_css"),
    [
        ("/web/debts?ledger_id=owner", "obligations", "/web/debts?ledger_id=owner", "/static/web/pages/debts.css"),
        ("/web/budgets?ledger_id=owner", "plans", "/web/budgets?ledger_id=owner", "/static/web/pages/budgets.css"),
    ],
)
def test_old_body_primary_pages_keep_legacy_page_css(
    web_client: TestClient,
    path: str,
    domain: str,
    primary_href: str,
    page_css: str,
) -> None:
    response = web_client.get(path)

    assert response.status_code == 200
    body = response.text
    assert f'data-domain="{domain}"' in body
    assert f'data-page="{domain}" data-page-level="primary"' in body
    assert '<span class="topbar-domain">' in body
    assert re.search(
        rf'href="{re.escape(primary_href)}"[^>]+aria-current="location"', body
    )

    # 壳 chrome 走 product 基座…
    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    # …正文仍是旧标记: 旧全局栈与本页页级 CSS 必须在场 (S3-R1 防回归钉),
    # 且对应 domain 模块不得双挂 (类名谱系碰撞 = 行格双失)。
    for legacy in ("/static/web/web.css", "/static/web/_base.css", "/static/web/_shell.css"):
        assert legacy in body
    assert f"{page_css}?v={STATIC_ASSET_VERSION}" in body
    assert "/static/web/product/domains/" not in body

    assert "<style" not in body
    _assert_shell_chrome_has_no_inline_style(body)


def test_confirmed_product_body_retires_legacy_stack_and_fake_filter(
    web_client: TestClient,
) -> None:
    """流水主入口迁入 product 正文栈，并退役只筛当前 50 行的假分类能力。"""
    confirmed = web_client.get("/web/confirmed?ledger_id=owner")
    assert confirmed.status_code == 200
    body = confirmed.text

    assert 'data-body-stack="product"' in body
    assert f"/static/web/product/domains/transactions.css?v={STATIC_ASSET_VERSION}" in body
    for retired in _RETIRED_GLOBAL_STACK:
        assert retired not in body
    assert "/static/web/pages/confirmed.css" not in body
    assert "/static/web/desktop/ledger-filter.js" not in body
    assert "data-ledger-filter" not in body

    assert '<span class="product-eyebrow">流水 / 已确认</span>' in body
    assert "ledger-stream" in body
    assert 'aria-label="本月概况"' in body
    assert "每日分布" in body
    assert "日历视图" not in body
    assert 'class="head"' not in body
    assert 'class="heatmap"' in body
    assert 'class="source-list"' in body
    assert "<style" not in body
    _assert_shell_chrome_has_no_inline_style(body)


def test_old_body_pages_keep_desktop_hook_and_legacy_drawer_source(
    web_client: TestClient,
) -> None:
    """S3-R2 (#256): 旧标记页补回 desktop-shell-active body hook (旧 _base/_misc/
    a11y 作用域规则依赖), 且旧 drawer 的样式来源 (components/drawer.css) 在场;
    product drawer 族规则已收窄到 [data-body-stack="product"], 不再吃旧 drawer。"""
    debts = web_client.get("/web/debts?ledger_id=owner")
    assert debts.status_code == 200
    body = debts.text
    body_tag = re.search(r"<body [^>]+>", body)
    assert body_tag is not None
    assert "desktop-shell-active" in body_tag.group(0)
    assert 'data-body-stack="product"' not in body_tag.group(0)
    assert "/static/web/components/drawer.css" in body

    css = web_client.get("/static/web/product/components.css")
    assert css.status_code == 200
    assert not re.search(r"^\.drawer\s*\{", css.text, re.M)
    assert not re.search(r"^\.drawer-head\s*\{", css.text, re.M)
    assert not re.search(r"^\.scrim\s*\{", css.text, re.M)
    assert '[data-body-stack="product"] .drawer {' in css.text
    assert '[data-body-stack="product"] .scrim {' in css.text
    assert '[data-body-stack="product"] .drawer-head {' in css.text


def test_overview_new_body_omits_desktop_hook(web_client: TestClient) -> None:
    """新标记页 (overview) 不挂 desktop-shell-active (其规则面向旧栈),
    改挂 data-body-stack="product" 作为 product drawer 族规则作用域锚。"""
    response = web_client.get("/web/overview?ledger_id=owner")
    assert response.status_code == 200
    body_tag = re.search(r"<body [^>]+>", response.text)
    assert body_tag is not None
    assert "desktop-shell-active" not in body_tag.group(0)
    assert 'data-body-stack="product"' in body_tag.group(0)


def test_product_shell_resets_legacy_sidebar_gap(web_client: TestClient) -> None:
    """S3-R2 (#256): 旧 _shell.css .sidebar{gap:28px} 在双栈下存活, product
    shell.css 必须显式重置 .sidebar gap (矿版间距全走子元素, 容器无 gap 语义)。"""
    css = web_client.get("/static/web/product/shell.css")
    assert css.status_code == 200
    assert re.search(r"\.sidebar\s*\{[^}]*gap:\s*0\s*;", css.text, re.S)


def test_overview_new_body_mounts_insights_module(web_client: TestClient) -> None:
    """overview (S2 新页, 正文已是新标记): 断旧栈, 挂 insights 域模块 +
    页级 pages/overview.css (样式归属裁决: 保留页级文件, 并入留给 S6)。"""
    response = web_client.get("/web/overview?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="insights"' in body
    assert 'data-page="insights" data-page-level="primary"' in body
    assert re.search(
        r'href="/web/overview\?ledger_id=owner"[^>]+aria-current="location"', body
    )

    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/domains/insights.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/pages/overview.css?v={STATIC_ASSET_VERSION}" in body

    # 新标记页断旧栈: 退役全局栈不得回流 (物理删除是独立后续片)。
    for retired in _RETIRED_GLOBAL_STACK:
        assert retired not in body
    for retired_page in (
        "/static/web/pages/dashboard.css",
        "/static/web/pages/pending.css",
        "/static/web/pages/confirmed.css",
        "/static/web/pages/budgets.css",
        "/static/web/pages/debts.css",
    ):
        assert retired_page not in body

    assert "<style" not in body
    _assert_shell_chrome_has_no_inline_style(body)


def test_product_shell_owns_month_picker_styles(web_client: TestClient) -> None:
    response = web_client.get("/web/confirmed?ledger_id=owner&month=2026-05")

    assert response.status_code == 200
    assert '<div class="month-picker">' in response.text
    # 月份选择器是壳 chrome, 样式归属 product/shell.css (旧 _shell.css 虽因
    # 正文旧标记分流而在场, 其旧规则对新的壳标记不生效)。
    assert "/static/web/product/shell.css" in response.text

    css = web_client.get("/static/web/product/shell.css")
    assert css.status_code == 200
    assert re.search(r"\.month-picker\s*\{", css.text)
    assert re.search(r"\.month-picker a\s*\{", css.text)
    assert re.search(r"\.month-picker \.label\s*\{", css.text)
    assert "font-family: var(--font-numeric)" in css.text
    assert "width: var(--space-9)" in css.text
    assert "height: var(--space-9)" in css.text


def test_primary_mutations_keep_real_csrf_and_occ_contracts(
    web_client: TestClient,
    identity,
) -> None:
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert pending.status_code == 200
    assert 'action="/web/review/bulk"' in pending.text
    assert re.search(
        r'name="csrf_token" value="[^"]+"',
        pending.text,
    )

    budgets = web_client.get("/web/budgets?ledger_id=owner")
    assert budgets.status_code == 200
    assert 'action="/web/budgets/save"' in budgets.text
    assert re.search(
        r'action="/web/budgets/save".*?name="csrf_token" value="[^"]+"',
        budgets.text,
        re.S,
    )

    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "产品壳测试",
            "category": "其他",
            "expense_time": "2026-07-18T08:00:00Z",
        },
    )
    assert created.status_code == 200
    expense_id = created.json()["id"]
    detail = web_client.get(
        f"/web/expenses/{expense_id}/edit"
        "?ledger_id=owner&return_to=confirmed"
    )

    assert detail.status_code == 200
    assert 'data-page="expense-detail" data-page-level="tertiary"' in detail.text
    assert "/static/web/product/detail.css" in detail.text
    assert f'href="/web/expenses/{expense_id}/correct?ledger_id=owner"' in detail.text
    correction = web_client.get(
        f"/web/expenses/{expense_id}/correct?ledger_id=owner"
    )
    assert correction.status_code == 200, correction.text
    assert f'action="/web/expenses/{expense_id}/corrections"' in correction.text
    for field in ("csrf_token", "expected_row_version", "idempotency_key"):
        assert re.search(rf'name="{field}" value="[^"]+"', correction.text)
    assert 'name="reason"' in correction.text


def test_secondary_product_routes_follow_canonical_ownership(
    web_client: TestClient,
) -> None:
    repayment = web_client.get("/web/repayment-drafts?ledger_id=owner")
    assert repayment.status_code == 200
    assert 'data-domain="obligations"' in repayment.text
    assert 'data-page="obligations" data-page-level="secondary"' in repayment.text
    assert '<span class="topbar-domain">往来</span>' in repayment.text
    assert '<span class="topbar-title">还款捕获</span>' in repayment.text

    # main 现状: /web/library 尚未存在 (C5c-1), 回收站是流水域普通二级页。
    recycle_bin = web_client.get("/web/recycle-bin?ledger_id=owner")
    assert recycle_bin.status_code == 200
    assert 'data-domain="transactions"' in recycle_bin.text
    assert 'data-page="transactions" data-page-level="secondary"' in recycle_bin.text


def test_viewer_primary_page_keeps_read_only_shell(web_client: TestClient) -> None:
    """viewer 角色壳契约: 五域导航保持可见 (只读可浏览), 顶栏/侧栏标注只读,
    正文前置 readonly-callout, 写面动作由页面隐藏 (本例以预算保存表单为证)。"""
    _demote_owner_ledger_to_viewer()

    page = web_client.get("/web/confirmed?ledger_id=owner")
    assert page.status_code == 200
    body = page.text
    assert 'data-domain="transactions"' in body
    assert 'class="readonly-callout"' in body
    assert "只读角色" in body
    sidebar = re.search(r'<aside class="sidebar">.*?</aside>', body, re.S)
    assert sidebar is not None
    for label in ["收件", "流水", "往来", "计划", "洞察"]:
        assert label in sidebar.group(0)
    assert "只读" in sidebar.group(0)  # account-summary 角色标注

    budgets = web_client.get("/web/budgets?ledger_id=owner")
    assert budgets.status_code == 200
    assert 'action="/web/budgets/save"' not in budgets.text


def test_product_css_modules_are_token_driven(web_client: TestClient) -> None:
    paths = [
        "/static/web/product/shell.css",
        "/static/web/product/components.css",
        "/static/web/product/detail.css",
        "/static/web/product/domains/inbox.css",
        "/static/web/product/domains/transactions.css",
        "/static/web/product/domains/obligations.css",
        "/static/web/product/domains/plans.css",
        "/static/web/product/domains/insights.css",
    ]

    for path in paths:
        response = web_client.get(path)
        assert response.status_code == 200, path
        css = response.text
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), path
        assert not re.search(r"\brgba?\(", css), path
