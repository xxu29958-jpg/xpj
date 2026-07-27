"""Tests for the 218-D S2 insights-domain home: GET /web/overview."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import LedgerMember
from app.routes import web_common
from app.services import backup_service
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

    # 页头本月脉搏状态行 + hero 关键数字层级 (exponent 投影: cur/int/dec 三段)。
    assert "本月概览" in body
    assert "笔已入账" in body
    assert "本月支出" in body
    assert "<small>¥</small>88<small>.00</small>" in body
    # 分类清单行走 minor_amount_label (符号+分组完整串)。
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
    assert "模块设置" in subnav.group(0)
    mobile_nav = re.search(r'<nav class="mobile-plan-nav".*?</nav>', body, re.S)
    assert mobile_nav is not None
    assert "总览" in mobile_nav.group(0)

    # 模块设置是独立的子导航项: cards 页它自己挂 aria-current=page, 总览不挂
    # (aria 语义 page 应指当前 URL — PR #253 复审收口)。
    cards_page = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert cards_page.status_code == 200
    cards_subnav = re.search(r'<nav class="nav-subnav".*?</nav>', cards_page.text, re.S)
    assert cards_subnav is not None
    assert re.search(
        r'href="/web/dashboard/cards\?ledger_id=owner"[^>]+aria-current="page"',
        cards_subnav.group(0),
    )
    assert not re.search(
        r'href="/web/overview\?ledger_id=owner"[^>]+aria-current="page"',
        cards_subnav.group(0),
    )
    cards_mobile_nav = re.search(r'<nav class="mobile-plan-nav".*?</nav>', cards_page.text, re.S)
    assert cards_mobile_nav is not None
    assert re.search(
        r'href="/web/dashboard/cards\?ledger_id=owner"[^>]+aria-current="page"',
        cards_mobile_nav.group(0),
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


def _save_card_layout(
    web_client: TestClient, *, ordered_keys: list[str], hidden: set[str] | None = None
) -> None:
    hidden_keys = hidden or set()
    saved = web_client.post(
        "/web/dashboard/cards/save",
        data={
            "ledger_id": "owner",
            "card_key": ordered_keys,
            "card_position": [str(index) for index, _key in enumerate(ordered_keys)],
            "visible_key": [key for key in ordered_keys if key not in hidden_keys],
        },
        follow_redirects=False,
    )
    assert saved.status_code in {303, 307}, saved.text


def test_overview_cards_render_in_persisted_order(web_client: TestClient) -> None:
    """PR #253 P2-1: 泳道内卡片顺序跟随模块设置的持久化 position。"""
    custom_order = ["recent_uploads", "pending"] + [
        key for key in WEB_CARD_KEYS if key not in {"recent_uploads", "pending"}
    ]
    _save_card_layout(web_client, ordered_keys=custom_order)

    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    assert resp.text.index('data-overview-card="recent_uploads"') < resp.text.index(
        'data-overview-card="pending"'
    )


def test_overview_lane_hidden_when_all_its_cards_hidden(web_client: TestClient) -> None:
    """PR #253 P2-2: 卡片全隐藏的泳道连标题一起不出。"""
    _save_card_layout(web_client, ordered_keys=WEB_CARD_KEYS, hidden={"pending", "recent_uploads"})

    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    assert "需处理" not in resp.text
    assert "本月事实" in resp.text
    assert "计划状态" in resp.text


def test_overview_viewer_empty_ledger_gets_readonly_onboarding(web_client: TestClient) -> None:
    """PR #253 P2-5: viewer 的空账本引导不引向写入口。"""
    _demote_owner_ledger_to_viewer()

    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    assert "先录入第一笔流水" in resp.text
    assert "只读成员" in resp.text
    # 只钉 onboarding 段 (侧边栏导航本身也有 pending/import 链接, 不属于本判定)。
    onboarding = re.search(
        r'<section class="product-state insight-onboarding".*?</section>', resp.text, re.S
    )
    assert onboarding is not None
    assert "/web/pending" not in onboarding.group(0)
    assert "/web/import" not in onboarding.group(0)


def test_overview_recent_additions_link_targets_confirmed(web_client: TestClient) -> None:
    """PR #253 P2-4: recent_count 口径含全部状态, 链接指向流水而非仅待处理。"""
    resp = web_client.get("/web/overview?ledger_id=owner")
    assert resp.status_code == 200
    card = re.search(r'data-overview-card="recent_uploads">.*?</article>', resp.text, re.S)
    assert card is not None
    assert 'href="/web/confirmed?ledger_id=owner"' in card.group(0)
    assert "/web/pending" not in card.group(0)


def test_overview_amounts_follow_home_currency_exponent(
    web_client: TestClient, monkeypatch: pytest.MonkeyPatch, *, identity
) -> None:
    """PR #253 P1-1: 零小数币种 (JPY) 的 hero/清单/图表投影按 exponent 格式化。"""
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        _seed_confirmed_expense(
            web_client, identity=identity, amount_cents=1234, merchant="すき家", category="餐饮"
        )
        resp = web_client.get("/web/overview?ledger_id=owner")
        assert resp.status_code == 200
        body = resp.text
        # hero: JPY 1234 minor = ¥1,234; 若错走 /100 会渲染成 ¥12.34。
        assert "<small>¥</small>1,234" in body
        assert "<small>¥</small>12<small>.34</small>" not in body
        # 分类清单行走 minor_amount_label。
        assert "¥1,234" in body
        # 环图数据带 exponent 感知的 amount_major (category-donut 优先消费)。
        assert '"amount_major": 1234' in body
    finally:
        get_settings.cache_clear()


def test_category_donut_escapes_tooltip_name_and_prefers_amount_major() -> None:
    """PR #253 P1-2/P1-1: 无 JS runner, 钉 category-donut.js 的安全/币种契约。"""
    source = (
        Path(__file__).resolve().parents[1]
        / "app/static/web/desktop/category-donut.js"
    ).read_text(encoding="utf-8")
    assert "app.escapeHtml(p.name)" in source
    assert "amount_major" in source


def test_dashboard_month_follows_accounting_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR #253 P2-7: cards.month / budget / goals 与 monthly_stats 同口径 (accounting tz)。"""
    monkeypatch.setenv("OCR_DEFAULT_TIMEZONE", "Pacific/Auckland")
    get_settings.cache_clear()
    seen: dict[str, str] = {}
    real_current_month = web_common.current_month

    def _spy_current_month(timezone_name: str) -> str:
        seen["month_tz"] = timezone_name
        return real_current_month(timezone_name)

    real_get_budget = web_common.get_monthly_budget

    def _spy_budget(db, *, tenant_id, month, timezone_name):
        seen["budget_tz"] = timezone_name
        return real_get_budget(db, tenant_id=tenant_id, month=month, timezone_name=timezone_name)

    real_list_goals = web_common.list_goals

    def _spy_goals(db, *, tenant_id, month, timezone_name):
        seen["goals_tz"] = timezone_name
        return real_list_goals(db, tenant_id=tenant_id, month=month, timezone_name=timezone_name)

    monkeypatch.setattr(web_common, "current_month", _spy_current_month)
    monkeypatch.setattr(web_common, "get_monthly_budget", _spy_budget)
    monkeypatch.setattr(web_common, "list_goals", _spy_goals)
    try:
        with SessionLocal() as db:
            web_common._dashboard_cards(db, "owner")
    finally:
        get_settings.cache_clear()
    assert seen == {
        "month_tz": "Pacific/Auckland",
        "budget_tz": "Pacific/Auckland",
        "goals_tz": "Pacific/Auckland",
    }


def test_latest_backup_lightweight_skips_per_file_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #253 P2-6: 状态卡口径按 mtime 取最新, 不逐文件 pg_restore 验证。"""
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path)
    older = tmp_path / "ticketbox-2026-07-01.dump"
    newer = tmp_path / "ticketbox-2026-07-20.dump"
    older.write_bytes(b"not-a-real-dump")
    newer.write_bytes(b"also-not-a-real-dump")
    old_time = time.time() - 86400 * 10
    os.utime(older, (old_time, old_time))

    def _boom(_path: Path) -> bool:
        raise AssertionError("validation must not run on the lightweight path")

    monkeypatch.setattr(backup_service, "is_postgres_backup_valid", _boom)

    entry = backup_service.latest_backup_lightweight()
    assert entry is not None
    assert entry.file_name == "ticketbox-2026-07-20.dump"
