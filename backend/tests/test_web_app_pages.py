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


def test_web_pending_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    assert "待确认" in resp.text


def test_web_pending_empty_all_offers_upload_entry_links(web_client: TestClient) -> None:
    """空账本待确认页(filter=all)的空态不止「解释发生了什么」,还给「下一步去哪」:
    iPhone 快捷指令配置 + CSV 导入两个直达链接(ledger_id 透传)。filter≠all 的空态
    是过滤无结果,不挂这些入口。撤掉空态链接本测试必红。

    判别用 /owner/upload-links —— 它只在本空态分支出现;/web/import 不能当判别,
    顶栏「导入 / 导出」按钮在任何状态下都有该链接。"""
    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    assert 'href="/owner/upload-links"' in body
    assert "从 CSV 导入" in body  # 空态内的 CSV 导入直达(措辞区别于顶栏「导入 / 导出」)

    # 过滤态空(疑似重复)只说没有匹配,不重复挂首日入口。
    filtered = web_client.get("/web/pending?ledger_id=owner&filter=duplicate")
    assert filtered.status_code == 200
    assert "没有匹配当前筛选的账单" in filtered.text
    assert 'href="/owner/upload-links"' not in filtered.text
    assert "从 CSV 导入" not in filtered.text


def test_web_confirmed_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed")
    assert resp.status_code == 200
    assert "已确认" in resp.text
    assert f"/static/web/_shell.css?v={STATIC_ASSET_VERSION}" in resp.text
    assert f"/static/shared/tokens.css?v={STATIC_ASSET_VERSION}" in resp.text


def test_web_mobile_primary_nav_contract(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    primary = re.search(r'<nav class="mobile-primary-nav".*?</nav>', body, re.S)
    assert primary is not None
    assert all(label in primary.group(0) for label in ["今日", "待确认", "账本", "洞察"])
    assert re.search(
        r'href="/web/confirmed\?ledger_id=owner"[^>]+aria-current="page"',
        primary.group(0),
    )

    desktop = re.search(r'<nav class="desktop-nav" aria-label="桌面入口">.*?</nav>', body, re.S)
    assert desktop is not None
    desktop_nav = re.sub(r"\{#.*?#\}", "", desktop.group(0), flags=re.S)
    assert "账单流" not in desktop_nav
    assert re.search(
        r'href="/web/confirmed\?ledger_id=owner"[^>]+aria-current="page"',
        desktop_nav,
    )
    _assert_in_order(
        desktop_nav,
        [
            "概览",
            "今日",
            "待确认",
            "已确认",
            "搜索",
            "清算",
            "疑似重复",
            "拆账收件箱",
            "已发拆账",
            "欠款",
            "欠我的",
            "还款捕获",
            "洞察与规划",
            "报表",
            "预算",
            "目标",
            "还债目标",
            "收入记录",
            "AI 预算建议",
            "固定支出",
            "治理",
            "分类",
            "商家",
            "标签",
            "规则",
            "数据体检",
            "回收站",
            "导入导出",
        ],
    )

    reports = web_client.get("/web/reports?ledger_id=owner")
    assert reports.status_code == 200
    reports_desktop = re.search(
        r'<nav class="desktop-nav" aria-label="桌面入口">.*?</nav>',
        reports.text,
        re.S,
    )
    assert reports_desktop is not None
    assert re.search(
        r'<details class="nav-group nav-group-collapsible"[^>]*open>\s*'
        r'<summary class="nav-group-title">洞察与规划</summary>',
        reports_desktop.group(0),
    )
    assert re.search(
        r'href="/web/reports\?ledger_id=owner"[^>]+aria-current="page"',
        reports_desktop.group(0),
    )


def test_web_mobile_more_nav_opens_for_secondary_pages(web_client: TestClient) -> None:
    resp = web_client.get("/web/search?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text

    assert re.search(r'<details class="mobile-more-nav"[^>]*open', body)
    assert re.search(
        r'class="mobile-more-link active" href="/web/search\?ledger_id=owner"[^>]+aria-current="page"',
        body,
    )


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
    assert "动态报表" in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/web/reports?month=2026-13",
        "/web/confirmed?month=0000-05",
        "/web/categories?month=2026-5",
    ],
)
def test_web_month_pages_reject_invalid_month_labels(
    web_client: TestClient, path: str
) -> None:
    resp = web_client.get(path)
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


def test_web_search_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/search?ledger_id=owner")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text


def test_web_nav_links_orphan_pages_reachable(web_client: TestClient) -> None:
    """孤儿页接回:四个有路由有模板但曾零入站链接的页面,从仪表盘一次 GET
    应能看到全部入口(侧栏治理组 ×2 + topbar 任务 + 页头卡片设置),且
    ledger_id 透传。撤掉任一模板链接本测试必红。"""
    resp = web_client.get("/web?ledger_id=owner")
    assert resp.status_code == 200
    assert 'href="/web/income-plans?ledger_id=owner"' in resp.text
    assert 'href="/web/budget-advise?ledger_id=owner"' in resp.text
    assert 'href="/web/tasks?ledger_id=owner"' in resp.text
    assert 'href="/web/dashboard/cards?ledger_id=owner"' in resp.text
