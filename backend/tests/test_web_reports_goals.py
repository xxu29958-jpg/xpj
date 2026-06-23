"""v0.9 /web reports and goals pages backed by real services."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_expense(
    client: TestClient,
    *, identity,
    amount_cents: int,
    merchant: str,
    category: str,
    expense_time: str,
    gray: bool = False,
) -> None:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.gray_app_headers if gray else identity.app_headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "expense_time": expense_time,
        },
    )
    assert response.status_code == 200, response.text


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_web_reports_and_goals_remote_return_403(client: TestClient) -> None:
    assert client.get("/web/reports").status_code == 403
    assert client.get("/web/goals").status_code == 403
    assert client.get("/web/reports/export.csv").status_code == 403


def test_web_reports_uses_real_report_service_and_csv(web_client: TestClient, *, identity) -> None:
    _create_expense(
        web_client,
        amount_cents=4200,
        merchant="星巴克",
        category="餐饮",
        expense_time="2026-05-03T12:00:00Z",
     identity=identity)
    _create_expense(
        web_client,
        amount_cents=1800,
        merchant="地铁",
        category="交通",
        expense_time="2026-05-04T12:00:00Z",
     identity=identity)
    _create_expense(
        web_client,
        amount_cents=9900,
        merchant="灰度账本商家",
        category="餐饮",
        expense_time="2026-05-05T12:00:00Z",
        gray=True,
     identity=identity)

    response = web_client.get(
        "/web/reports?ledger_id=owner&month=2026-05&granularity=week"
        "&ranking_metric=count&merchant_category=餐饮"
    )

    assert response.status_code == 200
    assert "动态报表" in response.text
    assert "月报摘要" in response.text
    assert "预算解释" in response.text
    assert "历史不足" in response.text
    assert "¥60.00" in response.text

    # ADR-0026: reports.js renders the charts from the injected JSON; verify the
    # data contract + that the category-filtered merchant ranking is correct.
    blob = re.search(
        r'<script type="application/json" id="reports-overview-data">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert blob is not None
    overview = json.loads(blob.group(1))
    assert {"trend", "merchant_ranking", "ranking_metric", "category_comparison"} <= overview.keys()
    assert overview["ranking_metric"] == "count"
    assert "星巴克" in [row["merchant"] for row in overview["merchant_ranking"]]
    assert "灰度账本商家" not in [row["merchant"] for row in overview["merchant_ranking"]]
    assert "分类环比" in response.text
    assert "灰度账本商家" not in response.text
    assert "/web/reports/export.csv" in response.text
    assert "granularity=week" in response.text
    assert "ranking_metric=count" in response.text
    assert "merchant_category=%E9%A4%90%E9%A5%AE" in response.text
    # ADR-0026: charts rendered by reports.js from #reports-overview-data.
    assert 'id="reports-overview-data"' in response.text
    assert 'id="reports-trend-chart"' in response.text
    assert 'id="reports-merchant-chart"' in response.text
    assert 'id="reports-category-chart"' in response.text
    assert 'id="reports-export-png"' in response.text
    assert "/static/web/reports.js" in response.text
    assert "商家排行" in response.text
    assert "/static/web/vendor/echarts.min.js" in response.text
    assert "/static/web/desktop.js" in response.text


def test_web_reports_absorbs_stats_top_expenses_and_seg_controls(
    web_client: TestClient, *, identity,
) -> None:
    # UI/UX 批 14: /web/stats 整页归并进 reports。stats 页唯一不可替代内容
    # 「大额支出 Top 5」迁来此处;granularity/ranking_metric 死 ctx 转正成 GET
    # 链接 segmented 控件。(独立成测,#49 教训:扩断言别把大测试推过 80 行债线。)
    _create_expense(
        web_client,
        amount_cents=4200,
        merchant="星巴克",
        category="餐饮",
        expense_time="2026-05-03T12:00:00Z",
     identity=identity)
    _create_expense(
        web_client,
        amount_cents=9900,
        merchant="灰度账本商家",
        category="餐饮",
        expense_time="2026-05-05T12:00:00Z",
        gray=True,
     identity=identity)

    response = web_client.get(
        "/web/reports?ledger_id=owner&month=2026-05&granularity=week&ranking_metric=count"
    )

    assert response.status_code == 200
    assert "大额支出" in response.text
    assert "星巴克" in response.text
    assert "灰度账本商家" not in response.text  # top-expenses 仍账本隔离
    # seg 控件 GET 链接：& 写字面量(模板里非变量输出,不经 autoescape)。
    assert (
        "/web/reports?ledger_id=owner&month=2026-05&granularity=week&ranking_metric=count"
        in response.text
    )
    assert "趋势粒度" in response.text
    assert "排行口径" in response.text
    assert "cdn.jsdelivr" not in response.text
    assert "unpkg.com" not in response.text
    assert "Bearer " not in response.text
    assert "UploadLink" not in response.text

    csv_response = web_client.get("/web/reports/export.csv?ledger_id=owner&month=2026-05")
    assert csv_response.status_code == 200
    assert "ticketbox-web-reports-2026-05-day.csv" in csv_response.headers["content-disposition"]
    assert "merchant_ranking,1,星巴克,4200,1" in csv_response.text
    assert "灰度账本商家" not in csv_response.text


def test_web_reports_renders_six_month_trend_chart_container(
    web_client: TestClient, *, identity
) -> None:
    """月度趋势卡(trend-chart.js)— f134d050 删容器后接回,数据与 KPI 同源
    six_month_trend。撤掉 reports.html 的容器本测试必红。"""
    _create_expense(
        web_client,
        amount_cents=4200,
        merchant="星巴克",
        category="餐饮",
        expense_time="2026-05-03T12:00:00Z",
        identity=identity,
    )
    response = web_client.get("/web/reports?ledger_id=owner&month=2026-05")
    assert response.status_code == 200
    assert 'id="chart-trend"' in response.text
    trend_blob = re.search(
        r'id="chart-trend"[^>]*\n?\s*data-series=\'(.*?)\'', response.text, re.DOTALL
    )
    assert trend_blob is not None
    six_month = json.loads(trend_blob.group(1))
    assert len(six_month) == 6
    assert {"month", "amount_yuan", "budget_yuan"} <= six_month[0].keys()


def test_web_reports_static_echarts_vendor_is_self_hosted(client: TestClient) -> None:
    script = client.get("/static/web/vendor/echarts.min.js")
    license_file = client.get("/static/web/vendor/echarts.LICENSE")
    reports_js = client.get("/static/web/reports.js")
    pending_css = client.get("/static/web/pages/pending.css")

    assert script.status_code == 200
    assert "Apache Software Foundation" in script.text[:5000]
    assert "sourceMappingURL" not in script.text[-2000:]
    assert license_file.status_code == 200
    assert "Apache License" in license_file.text
    assert reports_js.status_code == 200
    assert "reports-overview-data" in reports_js.text
    assert "rgba(15,23,42" not in reports_js.text
    assert pending_css.status_code == 200
    assert "#d6e3ee" not in pending_css.text
    assert "#d1e5d3" not in pending_css.text
    assert "cdn.jsdelivr" not in reports_js.text
    assert "unpkg.com" not in reports_js.text


def test_web_reports_selected_ledger_isolated(web_client: TestClient, *, identity) -> None:
    _create_expense(
        web_client,
        amount_cents=1200,
        merchant="OwnerOnly",
        category="餐饮",
        expense_time="2026-05-03T12:00:00Z",
     identity=identity)
    _create_expense(
        web_client,
        amount_cents=3400,
        merchant="TesterOnly",
        category="购物",
        expense_time="2026-05-03T12:00:00Z",
        gray=True,
     identity=identity)

    owner = web_client.get("/web/reports?ledger_id=owner&month=2026-05")
    tester = web_client.get("/web/reports?ledger_id=tester_1&month=2026-05")

    assert owner.status_code == 200
    assert tester.status_code == 200
    assert "OwnerOnly" in owner.text
    assert "TesterOnly" not in owner.text
    assert "TesterOnly" in tester.text
    assert "OwnerOnly" not in tester.text


def test_web_goals_create_archive_and_viewer_guard(web_client: TestClient, *, identity) -> None:
    _create_expense(
        web_client,
        amount_cents=64000,
        merchant="本月餐饮",
        category="餐饮",
        expense_time="2026-05-08T12:00:00Z",
     identity=identity)

    created = web_client.post(
        "/web/goals/create",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "name": "本月餐饮",
            "target_amount_yuan": "800.00",
            "category": "餐饮",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text

    page = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    assert "本月餐饮" in page.text
    assert "¥640.00 / ¥800.00" in page.text
    assert "80%" in page.text
    assert "保存目标" in page.text

    match = re.search(r"/web/goals/([^/]+)/archive", page.text)
    assert match, page.text[:1000]
    archived = web_client.post(
        f"/web/goals/{match.group(1)}/archive",
        data={"ledger_id": "owner", "month": "2026-05"},
        follow_redirects=False,
    )
    assert archived.status_code == 303, archived.text
    archived_page = web_client.get("/web/goals?ledger_id=owner&month=2026-05&include_archived=true")
    assert "已归档" in archived_page.text

    _demote_owner_ledger_to_viewer()
    viewer_page = web_client.get("/web/goals?ledger_id=owner&month=2026-05&include_archived=true")
    assert viewer_page.status_code == 200
    assert "只读角色" in viewer_page.text
    assert "保存目标" not in viewer_page.text
    denied = web_client.post(
        "/web/goals/create",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "name": "只读目标",
            "target_amount_yuan": "100.00",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"
