"""Tests for the 218-D S2 insights-domain home: GET /web/overview."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from app.services.time_service import current_month

WEB_CARD_KEYS = [
    "monthly_spend",
    "budget",
    "reports",
    "goals",
    "recurring",
    "pending",
    "recent_uploads",
    "backup_status",
    "device_status",
]


def _seed_confirmed_expense(client: TestClient, *, identity, amount_cents: int, merchant: str, category: str) -> None:
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "expense_time": f"{current_month('Asia/Shanghai')}-15T04:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text


def _seed_budget(client: TestClient, *, identity) -> None:
    month = current_month("Asia/Shanghai")
    resp = client.put(
        f"/api/budgets/monthly/{month}?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 100000,
            "category_budgets": [{"category": "餐饮", "amount_cents": 50000}],
        },
    )
    assert resp.status_code == 200, resp.text


def _seed_goal(client: TestClient, *, identity) -> None:
    month = current_month("Asia/Shanghai")
    resp = client.post(
        "/api/goals?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json={"name": "餐饮月度上限", "month": month, "target_amount_cents": 80000},
    )
    assert resp.status_code == 201, resp.text


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_overview_renders_hero_lanes_and_modules(web_client: TestClient, *, identity) -> None:
    _seed_confirmed_expense(web_client, identity=identity, amount_cents=8800, merchant="海底捞", category="餐饮")
    _seed_budget(web_client, identity=identity)
    _seed_goal(web_client, identity=identity)

    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    # 域归属 + 页面级 CSS 挂载。
    assert 'data-domain="insights"' in body
    assert "/static/web/pages/overview.css" in body

    # 页头本月脉搏状态行 + hero 关键数字层级。
    assert "本月概览" in body
    assert "笔已入账" in body
    assert "本月支出" in body
    assert "¥88.00" in body

    # 三泳道结构 + 预算/目标进度。
    for lane in ["需处理", "本月事实", "计划状态"]:
        assert lane in body
    assert "预算余量" in body
    assert "餐饮" in body
    assert "餐饮月度上限" in body
    assert "data-categories=" in body


def test_overview_empty_ledger_shows_onboarding(web_client: TestClient) -> None:
    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    # 空账本 = 设计过的引导态, 不是满屏 0。
    assert "当前账本还没有可分析的流水" in body
    assert "先录入第一笔流水" in body
    assert 'href="/web/pending?ledger_id=owner"' in body
    assert 'href="/web/import?ledger_id=owner"' in body
    # 零数据模块也给出口径说明而非空白。
    assert "还没有预算基线" in body
    assert "还没有分类结构" in body


def test_overview_selected_ledger_isolated(web_client: TestClient, *, identity) -> None:
    _seed_confirmed_expense(web_client, identity=identity, amount_cents=8800, merchant="海底捞", category="餐饮")

    resp = web_client.get("/web/overview?ledger_id=tester_1")
    assert resp.status_code == 200
    # tester_1 账本没有流水: 引导态出现, owner 账本的金额不可见。
    assert "先录入第一笔流水" in resp.text
    assert "¥88.00" not in resp.text
    assert "海底捞" not in resp.text


def test_overview_viewer_read_only(web_client: TestClient, *, identity) -> None:
    _seed_confirmed_expense(web_client, identity=identity, amount_cents=8800, merchant="海底捞", category="餐饮")
    _demote_owner_ledger_to_viewer()

    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    # viewer 看到同一份事实, 但页面没有任何写入口 (总览是纯只读页)。
    assert "¥88.00" in resp.text
    assert "<form" not in resp.text
    assert 'method="post"' not in resp.text.lower()


def test_overview_is_insights_nav_landing(web_client: TestClient) -> None:
    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    # 五域主导航的洞察落点 = /web/overview (desktop + 窄屏同构)。
    assert body.count('href="/web/overview?ledger_id=owner"') >= 2
    assert re.search(r'href="/web/overview\?ledger_id=owner"[^>]+aria-current="location"', body)
    # 洞察子导航首位 = 总览, 当前页 aria-current=page。
    subnav = re.search(r'<nav class="nav-subnav".*?</nav>', body, re.S)
    assert subnav is not None
    assert re.search(r'href="/web/overview\?ledger_id=owner"[^>]+aria-current="page"', subnav.group(0))
    assert "报表" in subnav.group(0)
    assert "数据体检" in subnav.group(0)
    mobile_nav = re.search(r'<nav class="mobile-plan-nav".*?</nav>', body, re.S)
    assert mobile_nav is not None
    assert "总览" in mobile_nav.group(0)

    # 模块设置页 (dashboard/cards) 归属总览: 子导航高亮总览。
    cards_page = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert cards_page.status_code == 200
    cards_subnav = re.search(r'<nav class="nav-subnav".*?</nav>', cards_page.text, re.S)
    assert cards_subnav is not None
    assert re.search(
        r'href="/web/overview\?ledger_id=owner"[^>]+aria-current="page"',
        cards_subnav.group(0),
    )

    # 报表页子导航不再抢占主落点: 报表仍是自己的 aria-current=page。
    reports_page = web_client.get("/web/reports?ledger_id=owner")
    assert reports_page.status_code == 200
    assert re.search(
        r'href="/web/reports\?ledger_id=owner"[^>]+aria-current="page"',
        reports_page.text,
    )


def test_overview_all_cards_hidden_shows_empty_state(web_client: TestClient) -> None:
    saved = web_client.post(
        "/web/dashboard/cards/save",
        data={
            "ledger_id": "owner",
            "card_key": WEB_CARD_KEYS,
            "card_position": [str(index) for index, _key in enumerate(WEB_CARD_KEYS)],
            "visible_key": [],
        },
        follow_redirects=False,
    )
    assert saved.status_code in {303, 307}, saved.text

    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    assert "总览暂时没有可见模块" in resp.text
    assert 'href="/web/dashboard/cards?ledger_id=owner"' in resp.text
