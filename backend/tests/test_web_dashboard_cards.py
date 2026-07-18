"""Representative /web dashboard-card integration coverage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember
from app.routes.web_app import _require_local as _web_require_local

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


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _dashboard_form_payload(
    ordered_keys: list[str],
    *,
    hidden: set[str] | None = None,
) -> dict[str, str | list[str]]:
    hidden_keys = hidden or set()
    return {
        "ledger_id": "owner",
        "card_key": ordered_keys,
        "card_position": [str(index) for index, _key in enumerate(ordered_keys)],
        "visible_key": [key for key in ordered_keys if key not in hidden_keys],
    }


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def _save_custom_dashboard_layout(web_client: TestClient) -> None:
    settings = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert settings.status_code == 200
    assert "概览内容" in settings.text
    assert 'name="card_key" value="pending"' in settings.text
    assert 'value="backup_status"' in settings.text
    assert 'value="device_status"' in settings.text
    assert "script-src 'self'" in settings.headers["Content-Security-Policy"]
    assert "/static/web/desktop/drag-reorder.js" not in settings.text
    assert "data-reorder-position" not in settings.text
    assert 'type="hidden" name="card_position"' in settings.text
    assert "需处理、本月事实、计划状态" in settings.text
    assert "<script>" not in settings.text

    custom_order = [
        "goals",
        "monthly_spend",
        "reports",
        "pending",
        "budget",
        "recurring",
        "recent_uploads",
        "backup_status",
        "device_status",
    ]
    saved = web_client.post(
        "/web/dashboard/cards/save",
        data=_dashboard_form_payload(custom_order, hidden={"reports"}),
        follow_redirects=False,
    )
    assert saved.status_code == 303, saved.text
    assert "ledger_id=owner" in saved.headers["location"]


def test_web_dashboard_cards_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/dashboard/data").status_code == 403
    assert client.get("/web/dashboard/cards").status_code == 403
    assert client.post("/web/dashboard/cards/save").status_code == 403
    assert client.post("/web/dashboard/cards/reset").status_code == 403


def test_web_dashboard_uses_saved_card_layout_and_reset(web_client: TestClient) -> None:
    _save_custom_dashboard_layout(web_client)

    dashboard = web_client.get("/web/overview?ledger_id=owner")
    assert dashboard.status_code == 200
    assert 'id="dashboard-app"' in dashboard.text
    assert "data-dashboard-rendered" in dashboard.text
    assert "data-dashboard-status" in dashboard.text
    assert "data-dashboard-retry" in dashboard.text
    assert "正在更新概览" in dashboard.text
    assert "data-dashboard-fallback" in dashboard.text
    assert dashboard.text.index('data-dashboard-card="pending"') < dashboard.text.index(
        'data-dashboard-card="monthly_spend"'
    )
    assert dashboard.text.index('data-dashboard-card="monthly_spend"') < dashboard.text.index(
        'data-dashboard-card="goals"'
    )
    assert 'data-dashboard-card="reports"' not in dashboard.text

    dashboard_data = web_client.get("/web/dashboard/data?ledger_id=owner")
    assert dashboard_data.status_code == 200, dashboard_data.text
    payload = dashboard_data.json()
    assert payload["selected_ledger_id"] == "owner"
    assert {"layout", "pending_count", "month"}.issubset(payload["cards"])
    assert "trend14" in payload and "category_share" in payload
    visible_keys = [item["key"] for item in payload["visible_layout"]]
    assert visible_keys[:2] == ["goals", "monthly_spend"]
    assert "reports" not in visible_keys

    hidden_all = web_client.post(
        "/web/dashboard/cards/save",
        data=_dashboard_form_payload(WEB_CARD_KEYS, hidden=set(WEB_CARD_KEYS)),
        follow_redirects=False,
    )
    assert hidden_all.status_code == 303, hidden_all.text
    empty_dashboard = web_client.get("/web/overview?ledger_id=owner")
    assert empty_dashboard.status_code == 200
    assert "概览暂时没有可见模块" in empty_dashboard.text
    # Empty state keeps the module-settings page reachable from Insights.
    assert 'href="/web/dashboard/cards?ledger_id=owner"' in empty_dashboard.text
    empty_data = web_client.get("/web/dashboard/data?ledger_id=owner")
    assert empty_data.status_code == 200, empty_data.text
    assert empty_data.json()["visible_layout"] == []

    reset = web_client.post(
        "/web/dashboard/cards/reset",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert reset.status_code == 303, reset.text

    reset_dashboard = web_client.get("/web/overview?ledger_id=owner")
    assert reset_dashboard.status_code == 200
    assert reset_dashboard.text.index('data-dashboard-card="pending"') < reset_dashboard.text.index(
        'data-dashboard-card="monthly_spend"'
    )
    assert 'data-dashboard-card="reports"' in reset_dashboard.text
    assert 'data-dashboard-card="backup_status"' not in reset_dashboard.text
    assert 'data-dashboard-card="device_status"' not in reset_dashboard.text

    reset_data = web_client.get("/web/dashboard/data?ledger_id=owner")
    assert reset_data.status_code == 200, reset_data.text
    reset_visible_keys = [item["key"] for item in reset_data.json()["visible_layout"]]
    assert "backup_status" not in reset_visible_keys
    assert "device_status" not in reset_visible_keys


def test_web_dashboard_cards_viewer_can_read_but_not_save(web_client: TestClient) -> None:
    _demote_owner_ledger_to_viewer()

    page = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert page.status_code == 200
    assert "只读角色" in page.text
    assert "保存显示设置</button>" not in page.text

    denied = web_client.post(
        "/web/dashboard/cards/save",
        data=_dashboard_form_payload(WEB_CARD_KEYS, hidden={"reports"}),
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "permission_denied"


def test_web_dashboard_static_js_wires_category_donut(client: TestClient) -> None:
    """分类环图接线静态钉:dashboard.js 必须渲染 #chart-category 容器并在
    fetch 渲染后补调 initCategoryDonut(仪表盘晚于 desktop.js boot());
    category-donut.js 必须读 category_share 的现成键(name/amount_yuan,
    元而非分——cents 直出会把展示放大 100 倍)。撤任一接线行本测试红。"""
    dashboard_js = client.get("/static/web/desktop/dashboard.js")
    assert dashboard_js.status_code == 200
    assert "chart-category" in dashboard_js.text
    assert "initCategoryDonut" in dashboard_js.text
    assert "data-categories" in dashboard_js.text
    assert "SLOW_LOAD_MS = 2000" in dashboard_js.text
    assert "FALLBACK_LOAD_MS = 8000" in dashboard_js.text
    assert "AbortController" in dashboard_js.text
    assert 'data-dashboard-state", "slow"' in dashboard_js.text
    assert "data-dashboard-retry" in dashboard_js.text
    assert "product-panel product-panel--padded" in dashboard_js.text
    assert "insight-sequence" in dashboard_js.text
    assert "DASHBOARD_LANES" in dashboard_js.text
    assert "style." not in dashboard_js.text
    assert 'setAttribute("style"' not in dashboard_js.text
    assert '"dt-' not in dashboard_js.text
    assert "createElementNS" not in dashboard_js.text

    donut_js = client.get("/static/web/desktop/category-donut.js")
    assert donut_js.status_code == 200
    assert "d.name" in donut_js.text
    assert "d.amount_yuan" in donut_js.text
    assert "d.amount_cents" not in donut_js.text


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_web_overview_first_day_shows_product_entry_links_until_first_expense(
    web_client: TestClient, identity
) -> None:
    """首日引导:全新账本(lifetime exists()=False)的洞察概览给出产品内整理入口,
    而不是跳去 Owner 技术控制台;有了第一笔账单后回到稳态账面摘要。

    page-header 在 JS 渲染区外服务端无条件渲染,所以这条路由级断言对脚本开/关
    两路径都成立。撤掉首日分支或重新暴露技术入口本测试必红。"""
    first_day = web_client.get("/web/overview?ledger_id=owner")
    assert first_day.status_code == 200
    body = first_day.text
    assert '<h1 class="page-title" id="overview-title">本月概览</h1>' in body
    assert "当前账本还没有可分析的流水" in body
    assert "先录入第一笔流水" in body
    # 新用户从产品内收件箱或 CSV 导入开始，不暴露 Owner 控制台。
    assert 'href="/web/pending?ledger_id=owner"' in body
    assert 'href="/web/import?ledger_id=owner"' in body
    assert 'href="/owner/pairing"' not in body
    assert 'href="/owner/upload-links"' not in body

    # 上传一张截图(经 UploadLink 落 owner 账本的 pending)→ 不再是首日。
    upload = web_client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=_TINY_PNG,
    )
    assert upload.status_code == 200, upload.text

    after = web_client.get("/web/overview?ledger_id=owner")
    assert after.status_code == 200
    after_body = after.text
    assert "0 笔已入账 · 1 笔待处理" in after_body
    assert "当前账本还没有形成可分析的数据" not in after_body
    assert 'href="/owner/pairing"' not in after_body
