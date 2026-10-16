"""Delivered Web navigation, assets, read-only access and native form contracts."""

from __future__ import annotations

import re
from collections.abc import Iterator
from uuid import uuid4

import pytest
from _web_bulk_test_support import seed_pending_with_amount as _seed_pending_with_amount
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.version import STATIC_ASSET_VERSION


@pytest.fixture
def owner_ledger_viewer() -> Iterator[None]:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        original_role = member.role
        member.role = "viewer"
        db.commit()
    try:
        yield
    finally:
        with SessionLocal() as db:
            member = db.scalar(
                select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1)
            )
            assert member is not None
            member.role = original_role
            db.commit()


def test_product_shell_exposes_local_appearance_axes_without_fake_upload_entry(
    web_client: TestClient,
) -> None:
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    assert "data-appearance-trigger" in body
    assert 'id="appearance-popover"' in body
    assert 'data-theme-mode="paper"' in body
    assert 'data-theme-mode="midnight"' in body
    assert "data-texture-mode" in body
    assert "data-accent-mode" in body
    assert "自定义背景" not in body
    assert "即将支持" not in body

    theme_js = web_client.get("/static/web/desktop/theme.js")
    assert theme_js.status_code == 200


def test_product_shell_restores_appearance_axes_via_external_bootstrap(
    web_client: TestClient,
) -> None:
    """质感/强调色在首屏前由外部 appearance-bootstrap.js 恢复 —— inline
    bootstrap 在 script-src 'self' 下静默死亡; 外部文件由 base 与 login 共享。"""
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    assert '<script src="/static/web/appearance-bootstrap.js' in response.text
    assert "localStorage" not in response.text


def test_product_shell_mobile_task_order_and_capture_search_entries(
    web_client: TestClient,
    *, identity,
) -> None:
    """W1 IA-B: 移动 chrome = 单顶带 + 底部五域 nav; 域内页签移入 main 首元素
    随页滚动, 五域主导航唯一且在 main 之后。topbar 携带真实入口: 收票 (writer
    可见的 GET 导航, upload command owner 不变) 与搜索。"""
    empty = web_client.get("/web/pending?ledger_id=owner")
    assert empty.status_code == 200
    empty_main = re.search(r"<main\b[^>]*>(.*?)</main>", empty.text, re.S)
    assert empty_main is not None
    assert 'aria-label="当前领域页面"' not in empty_main.group(1)
    assert "收第一张小票" in empty.text
    _seed_pending_with_amount(web_client, "12.00", "待确认的小票", identity=identity)
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text

    # 有待处理小票时保留域内页签；空态只显示唯一五域导航和真实采集入口。
    assert body.count('aria-label="产品领域"') == 1
    main = re.search(r"<main\b[^>]*>(.*?)</main>", body, re.S)
    assert main is not None
    assert main.group(1).count('aria-label="当前领域页面"') == 1
    assert body.index('</main>') < body.index('aria-label="产品领域"')

    topbar = re.search(r'<header\b[^>]*>.*?</header>', body, re.S)
    assert topbar is not None
    topbar_html = topbar.group(0)
    assert 'href="/web/pending?ledger_id=owner#capture"' in topbar_html
    assert "拍照或选小票" in topbar_html
    assert 'aria-label="新增记录"' in topbar_html
    assert 'href="/web/search?ledger_id=owner"' in topbar_html


def test_product_shell_capture_entry_hidden_for_viewer(
    web_client: TestClient,
    owner_ledger_viewer: None,
) -> None:
    """W1: 收票是写入口, viewer 不渲染; 搜索只读可用, 保留。"""
    response = web_client.get("/web/pending?ledger_id=owner")
    assert response.status_code == 200
    topbar = re.search(r'<header\b[^>]*>.*?</header>', response.text, re.S)
    assert topbar is not None
    topbar_html = topbar.group(0)
    assert "#capture" not in topbar_html
    assert "拍照或选小票" not in topbar_html
    assert 'href="/web/search?ledger_id=owner"' in topbar_html


def test_account_switcher_is_native_disclosure_without_false_local_logout(
    web_client: TestClient,
) -> None:
    """W1 repair: 「我」面板是 <details> 原生披露 (无 JS 可开合/键盘/读屏诚实),
    不再是 clickable div；loopback Owner 没有 browser session，因此不能伪装
    出一个实际无法退出本机 Owner 面的登出动作。切换账本 rows 保持真实链接。"""
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text

    assert re.search(r'<details\b[^>]*>\s*<summary[^>]+aria-label="账户与账本"', body)
    assert 'action="/web/auth/logout"' not in body
    assert "退出登录" not in body
    # 账本切换 rows 仍是真实 GET 链接, 不被披露组件吃掉
    assert re.search(r'<a\b[^>]*href="/web/pending\?ledger_id=', body) is not None


@pytest.mark.parametrize(
    ("path", "page_level"),
    [
        ("/web/debts?ledger_id=owner", "primary"),
        ("/web/receivables?ledger_id=owner", "secondary"),
        ("/web/debts/new?ledger_id=owner", "tertiary"),
    ],
)
def test_debt_core_pages_deliver_domain_navigation_and_assets(
    web_client: TestClient,
    path: str,
    page_level: str,
) -> None:
    response = web_client.get(path)

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="obligations"' in body
    assert f'data-page="obligations" data-page-level="{page_level}"' in body
    assert re.search(
        r'href="/web/debts\?ledger_id=owner"[^>]+aria-current="location"',
        body,
    )
    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/domains/obligations.css?v={STATIC_ASSET_VERSION}" in body


def test_budget_page_delivers_its_tasks_and_assets(web_client: TestClient) -> None:
    response = web_client.get("/web/budgets?ledger_id=owner&month=2026-05")

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="plans"' in body
    assert 'data-page="plans" data-page-level="primary"' in body
    assert f"/static/web/product/domains/plans.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/desktop/budgets.js?v={STATIC_ASSET_VERSION}" in body
    assert "这个月，心里有数" in body


def test_confirmed_page_delivers_current_tasks_and_assets(
    web_client: TestClient,
) -> None:
    confirmed = web_client.get("/web/confirmed?ledger_id=owner")
    assert confirmed.status_code == 200
    body = confirmed.text

    assert f"/static/web/product/domains/transactions.css?v={STATIC_ASSET_VERSION}" in body

    assert "流水" in body
    assert 'aria-label="本月概况"' in body
    assert "每日分布" in body


def test_overview_delivers_current_navigation_and_assets(web_client: TestClient) -> None:
    response = web_client.get("/web/overview?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    assert 'data-domain="insights"' in body
    assert 'data-page="insights" data-page-level="primary"' in body
    assert re.search(r'href="/web/overview\?ledger_id=owner"[^>]+aria-current="location"', body)

    assert f"/static/web/product/shell.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/components.css?v={STATIC_ASSET_VERSION}" in body
    assert f"/static/web/product/domains/insights.css?v={STATIC_ASSET_VERSION}" in body


def test_product_shell_self_hosts_consumer_fonts(web_client: TestClient) -> None:
    page = web_client.get("/web/confirmed?ledger_id=owner")
    assert page.status_code == 200
    assert "/static/web/fonts/fonts.css" in page.text
    css = web_client.get("/static/web/fonts/fonts.css")
    assert css.status_code == 200
    sources = re.findall(r"src:\s*url\(([^)]+)\)", css.text)
    assert sources
    for source in sources:
        assert re.fullmatch(r"[A-Za-z0-9-]+\.woff2", source), source
        font = web_client.get(f"/static/web/fonts/{source}")
        assert font.status_code == 200, source
        assert font.content.startswith(b"wOF2"), source


def test_primary_mutations_keep_real_csrf_and_occ_contracts(
    web_client: TestClient,
    identity,
) -> None:
    pending_id = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert pending.status_code == 200
    assert 'action="/web/review/bulk"' in pending.text
    assert f'data-expense-id="{pending_id}"' in pending.text
    assert 'name="expense_snapshot"' in pending.text
    assert 'data-row-version="' in pending.text
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
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 1234,
            "merchant": "产品壳测试",
            "category": "其他",
            "expense_time": "2026-07-18T08:00:00Z",
        },
    )
    assert created.status_code == 200
    expense_id = created.json()["id"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=confirmed")

    assert detail.status_code == 200
    assert 'data-page="expense-detail" data-page-level="tertiary"' in detail.text
    assert "/static/web/product/detail.css" in detail.text
    correction_url = f"/web/expenses/{expense_id}/correct?ledger_id=owner&return_to=confirmed"
    assert (f'href="/web/expenses/{expense_id}/correct?ledger_id=owner&amp;return_to=confirmed"') in detail.text
    correction = web_client.get(correction_url)
    assert correction.status_code == 200, correction.text
    assert f'action="/web/expenses/{expense_id}/corrections"' in correction.text
    for field in ("csrf_token", "expected_row_version", "idempotency_key"):
        assert re.search(rf'name="{field}" value="[^"]+"', correction.text)
    assert 'name="reason"' in correction.text
    assert 'name="return_to" value="confirmed"' in correction.text


def test_secondary_product_routes_follow_canonical_ownership(
    web_client: TestClient,
) -> None:
    repayment = web_client.get("/web/repayment-drafts?ledger_id=owner")
    assert repayment.status_code == 200
    assert 'data-domain="obligations"' in repayment.text
    assert 'data-page="obligations" data-page-level="secondary"' in repayment.text
    assert "往来" in repayment.text
    assert "还款采集" in repayment.text

    # Recovery is a focused task under the shipped reference library.
    recycle_bin = web_client.get("/web/recycle-bin?ledger_id=owner")
    assert recycle_bin.status_code == 200
    assert 'data-domain="transactions"' in recycle_bin.text
    assert 'data-page="transactions" data-page-level="tertiary"' in recycle_bin.text
    assert 'href="/web/library?ledger_id=owner"' in recycle_bin.text


def test_viewer_primary_page_keeps_read_only_shell(
    web_client: TestClient,
    owner_ledger_viewer: None,
) -> None:
    """viewer 角色壳契约: 五域导航保持可见 (只读可浏览), 顶栏/侧栏标注只读,
    正文前置只读提示, 写面动作由页面隐藏 (本例以预算保存表单为证)。"""
    page = web_client.get("/web/confirmed?ledger_id=owner")
    assert page.status_code == 200
    body = page.text
    assert 'data-domain="transactions"' in body
    assert re.search(r'role="status"[^>]*>.*?你可以查看这本账', body, re.S)
    assert "你可以查看这本账" in body
    assert "如需修改，请联系拥有者。" in body
    sidebar = re.search(r'<aside\b[^>]*>.*?</aside>', body, re.S)
    assert sidebar is not None
    for label in ["收件", "流水", "往来", "计划", "洞察"]:
        assert label in sidebar.group(0)
    assert "只读" in sidebar.group(0)  # account-summary 角色标注

    budgets = web_client.get("/web/budgets?ledger_id=owner")
    assert budgets.status_code == 200
    assert 'action="/web/budgets/save"' not in budgets.text
