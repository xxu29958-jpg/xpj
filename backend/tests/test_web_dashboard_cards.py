"""Representative /web dashboard-card integration coverage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember
from app.routes import web_common
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
    assert client.get("/web/dashboard/cards").status_code == 403
    assert client.post("/web/dashboard/cards/save").status_code == 403
    assert client.post("/web/dashboard/cards/reset").status_code == 403


def test_web_dashboard_cards_back_link_targets_overview(web_client: TestClient) -> None:
    """S4-R2: /web 根 303→pending 后, 模块设置的返回链指向卡片归属页
    /web/overview, 文案「返回总览」, 不再把用户带进收件域。"""
    page = web_client.get("/web/dashboard/cards?ledger_id=owner")
    assert page.status_code == 200
    assert 'href="/web/overview?ledger_id=owner"' in page.text
    assert "返回总览" in page.text
    assert "返回仪表盘" not in page.text
    assert 'href="/web?ledger_id=owner"' not in page.text


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

    # 218-D S4: /web 根改向收件域后, 卡片布局的 HTML 承接面是 /web/overview
    # (S2 泳道: 泳道归属固定, 组内卡片按持久化 position 渲染, 全隐藏卡不出)。
    # 顺序断言因此落在同泳道内 (goals/budget/recurring 同属「计划状态」)。
    overview = web_client.get("/web/overview?ledger_id=owner")
    assert overview.status_code == 200
    assert overview.text.index('data-overview-card="goals"') < overview.text.index(
        'data-overview-card="budget"'
    )
    assert overview.text.index('data-overview-card="budget"') < overview.text.index(
        'data-overview-card="recurring"'
    )
    assert 'data-overview-card="reports"' not in overview.text

    with SessionLocal() as db:
        payload = web_common._dashboard_data_payload(db, "owner")
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
    empty_overview = web_client.get("/web/overview?ledger_id=owner")
    assert empty_overview.status_code == 200
    assert "总览暂时没有可见模块" in empty_overview.text
    # 空态必须给出「模块设置」入口(孤儿页接回:服务端 fallback 分支)。
    assert 'href="/web/dashboard/cards?ledger_id=owner"' in empty_overview.text
    with SessionLocal() as db:
        assert web_common._dashboard_data_payload(db, "owner")["visible_layout"] == []

    reset = web_client.post(
        "/web/dashboard/cards/reset",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert reset.status_code == 303, reset.text

    reset_overview = web_client.get("/web/overview?ledger_id=owner")
    assert reset_overview.status_code == 200
    # 默认序在同泳道 (「本月事实」) 内恢复: monthly_spend 在 reports 前。
    assert reset_overview.text.index('data-overview-card="monthly_spend"') < reset_overview.text.index(
        'data-overview-card="reports"'
    )
    assert 'data-overview-card="reports"' in reset_overview.text


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


_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_web_overview_first_day_shows_entry_links_until_first_expense(
    web_client: TestClient, identity
) -> None:
    """首日引导:全新账本(lifetime exists()=False)的总览页给出「先录入第一笔
    流水」引导与产品内进票口(待我处理 / 导入历史记录),而不是满屏 0;有了第一笔
    账单后回到稳态账面摘要、引导消失。

    218-D S4: /web 根改向收件域, 原仪表盘首日分支不再直接
    服务; 首日引导的承接面是 /web/overview (S2 起就有 has_any_expense 分支)。
    引导在 JS 渲染区外服务端无条件渲染,所以这条路由级断言对脚本开/关两路径
    都成立。撤掉首日分支或任一入口链接本测试必红。"""
    first_day = web_client.get("/web/overview?ledger_id=owner")
    assert first_day.status_code == 200
    body = first_day.text
    assert "先录入第一笔流水" in body
    # 两个产品内进票口(ledger_id 透传)。
    assert 'href="/web/pending?ledger_id=owner"' in body
    assert 'href="/web/import?ledger_id=owner"' in body

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
    assert "1 笔待处理" in after_body
    assert "先录入第一笔流水" not in after_body
