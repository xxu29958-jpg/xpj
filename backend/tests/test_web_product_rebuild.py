"""Product-shell contracts for the Web UI/IA rebuild (218-D S3, 移植自产品矿并适配 main).

本片只落「壳基座」: base.html / _sidebar_nav.html 重写 + product 设计系统 CSS
+ web_common 展示 helper。页面模板重绘属 S4+ 各域片, 因此矿版测试中与页面内容
重写耦合的用例 (新文案标题、dt-* DOM 清除、正文零内联样式) 不在本片断言——
本片钉的是壳契约: 五域 primary 页挂新栈且断旧栈、页级三态 data 属性、
三级页挂 detail.css、壳 chrome 无内联样式、product CSS 全部 token 驱动。

与矿版的分歧 (以 main 事实为准):
- /web/library 路由属 C5c-1, 资料库聚合断言不移植; 回收站在 main 仍是流水域
  普通二级页 (矿归 library-detail 三级)。
- overview 页级 pages/overview.css 保留 (S2 适配标记矿域模块未覆盖),
  因此 retired 清单对 overview 允许该一个文件。
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


@pytest.mark.parametrize(
    ("path", "domain", "primary_href"),
    [
        ("/web/pending?ledger_id=owner", "inbox", "/web/pending?ledger_id=owner"),
        ("/web/confirmed?ledger_id=owner", "transactions", "/web/confirmed?ledger_id=owner"),
        ("/web/debts?ledger_id=owner", "obligations", "/web/debts?ledger_id=owner"),
        ("/web/budgets?ledger_id=owner", "plans", "/web/budgets?ledger_id=owner"),
        ("/web/overview?ledger_id=owner", "insights", "/web/overview?ledger_id=owner"),
    ],
)
def test_primary_domains_render_new_modular_product_shell(
    web_client: TestClient,
    path: str,
    domain: str,
    primary_href: str,
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

    # The rebuilt shell mounts the product design system…
    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/domains/{domain}.css?v={STATIC_ASSET_VERSION}" in body

    # …and a migrated primary page owns its presentation module: the retired
    # global stack cannot silently leak back in. (物理删除是独立后续片, 本片只
    # 钉「primary 页不引旧栈」。)
    for retired in _RETIRED_GLOBAL_STACK:
        assert retired not in body
    if domain == "insights":
        # overview 样式归属裁决: 保留 S2 页级文件 (见模块 docstring)。
        assert f"/static/web/pages/overview.css?v={STATIC_ASSET_VERSION}" in body
    else:
        assert "/static/web/pages/" not in body

    assert "<style" not in body

    # 壳 chrome (侧边导航 + 顶栏) 零内联样式; 页面正文残留的数据驱动内联
    # (进度条宽度等) 随 S4+ 页面重绘清除, 本片不钉。
    sidebar = re.search(r'<aside class="sidebar">.*?</aside>', body, re.S)
    assert sidebar is not None
    assert 'style="' not in sidebar.group(0)
    topbar = re.search(r'<header class="product-topbar">.*?</header>', body, re.S)
    assert topbar is not None
    assert 'style="' not in topbar.group(0)


def test_product_shell_owns_month_picker_styles(web_client: TestClient) -> None:
    response = web_client.get("/web/confirmed?ledger_id=owner&month=2026-05")

    assert response.status_code == 200
    assert '<div class="month-picker">' in response.text
    assert "/static/web/product/shell.css" in response.text
    assert "/static/web/_shell.css" not in response.text

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
    assert re.search(
        r'action="/web/expenses/\d+/save".*?'
        r'name="csrf_token" value="[^"]+".*?'
        r'name="expected_row_version" value="[^"]+"',
        detail.text,
        re.S,
    )


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
