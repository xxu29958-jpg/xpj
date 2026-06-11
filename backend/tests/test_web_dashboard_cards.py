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


def test_web_dashboard_cards_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/dashboard/data").status_code == 403
    assert client.get("/web/dashboard/cards").status_code == 403
    assert client.post("/web/dashboard/cards/save").status_code == 403
    assert client.post("/web/dashboard/cards/reset").status_code == 403


def test_web_dashboard_uses_saved_card_layout_and_reset(web_client: TestClient) -> None:
    settings = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert settings.status_code == 200
    assert "仪表盘卡片" in settings.text
    assert 'name="card_key" value="pending"' in settings.text

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

    dashboard = web_client.get("/web?ledger_id=owner")
    assert dashboard.status_code == 200
    assert 'id="dashboard-app"' in dashboard.text
    assert "dashboard-skeleton-grid" in dashboard.text
    assert "data-dashboard-fallback" in dashboard.text
    assert dashboard.text.index('data-dashboard-card="goals"') < dashboard.text.index(
        'data-dashboard-card="monthly_spend"'
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
    empty_dashboard = web_client.get("/web?ledger_id=owner")
    assert empty_dashboard.status_code == 200
    assert "当前仪表盘没有可见卡片" in empty_dashboard.text
    # 空态必须给出「仪表盘卡片」入口(孤儿页接回:服务端 fallback 分支)。
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

    reset_dashboard = web_client.get("/web?ledger_id=owner")
    assert reset_dashboard.status_code == 200
    assert reset_dashboard.text.index('data-dashboard-card="monthly_spend"') < reset_dashboard.text.index(
        'data-dashboard-card="pending"'
    )
    assert 'data-dashboard-card="reports"' in reset_dashboard.text


def test_web_dashboard_cards_viewer_can_read_but_not_save(web_client: TestClient) -> None:
    _demote_owner_ledger_to_viewer()

    page = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert page.status_code == 200
    assert "只读角色" in page.text
    assert "保存卡片</button>" not in page.text

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

    donut_js = client.get("/static/web/desktop/category-donut.js")
    assert donut_js.status_code == 200
    assert "d.name" in donut_js.text
    assert "d.amount_yuan" in donut_js.text
    assert "d.amount_cents" not in donut_js.text
