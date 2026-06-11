"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


def test_web_pending_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    assert "待确认" in resp.text


def test_web_confirmed_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed")
    assert resp.status_code == 200
    assert "已确认" in resp.text


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


def test_web_stats_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/stats?month=2026-05")
    assert resp.status_code == 200
    assert "月度统计" in resp.text


def test_web_stats_reports_recurring_candidate_errors(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routes import web_stats as web_stats_module

    def fail_recurring_candidates(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_stats_module, "recurring_candidates", fail_recurring_candidates)

    resp = web_client.get("/web/stats?month=2026-05")

    assert resp.status_code == 200
    assert "固定支出候选分析暂时不可用" in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/web/stats?month=2026-13",
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
