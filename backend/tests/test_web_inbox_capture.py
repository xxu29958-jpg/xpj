from __future__ import annotations

import re
from pathlib import Path

from _web_bulk_test_support import create_pending as _create_pending
from _web_bulk_test_support import seed_pending_with_amount as _seed_pending_with_amount
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routes.uploads as upload_routes
import app.routes.web_inbox_capture as web_inbox_capture_routes
from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.routes._upload_request import handle_upload
from tests._infra.assets import PNG_BYTES


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_web_pending_upload_uses_shared_owner_and_creates_real_pending_expense(
    web_client: TestClient,
) -> None:
    assert upload_routes.handle_upload is handle_upload
    assert web_inbox_capture_routes.handle_upload is handle_upload

    response = web_client.post(
        "/web/pending/upload",
        data={"ledger_id": "owner", "timezone": "Asia/Shanghai"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/web/pending?")
    assert "ledger_id=owner" in response.headers["location"]

    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense)
            .where(Expense.tenant_id == "owner", Expense.source == "网页上传")
            .order_by(Expense.id.desc())
            .limit(1)
        )
        assert expense is not None
        assert expense.status == "pending"
        assert expense.image_path is not None
        assert expense.image_hash


def test_web_pending_upload_rejects_viewer_before_saving(
    web_client: TestClient,
) -> None:
    _demote_owner_ledger_to_viewer()

    response = web_client.post(
        "/web/pending/upload",
        data={"ledger_id": "owner", "timezone": "Asia/Shanghai"},
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(Expense.id).where(
                    Expense.tenant_id == "owner",
                    Expense.source == "网页上传",
                )
            )
            is None
        )


def test_inbox_pending_header_has_native_upload_form_and_flat_queue_summary(
    web_client: TestClient, *, identity
) -> None:
    """K3: 页头给 writer 原生无 JS 上传表单 (multipart → /web/pending/upload,
    显式 csrf/ledger/hidden timezone, accept=image/* required, 主按钮上传小票),
    导入与导出保留为次级入口; 三数字概况墙压平为一句队列小结, 可行动计数
    只留在筛选 pill 上。"""
    _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    form = re.search(
        r'<form class="inbox-upload-form" method="post" action="/web/pending/upload"'
        r' enctype="multipart/form-data">.*?</form>',
        body,
        re.S,
    )
    assert form is not None
    form_html = form.group(0)
    assert 'name="csrf_token"' in form_html
    assert 'name="ledger_id" value="owner"' in form_html
    assert 'name="timezone"' in form_html
    assert "data-inbox-timezone" in form_html
    assert re.search(
        r'<input class="inbox-upload-file" type="file" name="file"'
        r' accept="image/\*" required',
        form_html,
    )
    assert "上传小票" in form_html
    assert "导入与导出" in body

    assert "inbox-summary-item" not in body
    assert "inbox-queue-line" in body
    assert "笔待整理" in body

    static_root = Path(__file__).resolve().parents[1] / "app" / "static" / "web"
    core_js = (static_root / "desktop" / "core.js").read_text(encoding="utf-8")
    assert "initInboxCapture" in core_js
    assert "data-inbox-timezone" in core_js
    assert ".submit(" not in core_js
    desktop_js = (static_root / "desktop.js").read_text(encoding="utf-8")
    assert 'call("initInboxCapture");' in desktop_js


def test_inbox_pending_row_single_priority_status_and_one_writer_action(
    web_client: TestClient, *, identity
) -> None:
    """K3: 每行只渲染一个优先级状态 pill (缺金额 > 疑似重复 > 缺商家 > 缺分类 >
    待汇率 > 可确认), 且状态/动作收在链接外的 .exp-flags 兄弟槽; ready 行给
    与批量条同 OCC 合同的单行 confirm_ready 表单, 待修行给编辑页修复链接。"""
    ready_id = _seed_pending_with_amount(web_client, "9.00", "盒马", identity=identity)
    broken_id = _create_pending(web_client, identity=identity)
    body = web_client.get("/web/pending?ledger_id=owner").text

    ready_row = re.search(
        rf'<div class="exp-row" data-expense-id="{ready_id}">.*?</a>\s*'
        r'<div class="exp-flags">(.*?)</div>\s*</div>',
        body,
        re.S,
    )
    assert ready_row is not None
    ready_flags = ready_row.group(1)
    assert ready_flags.count("product-status") == 2
    assert "可确认" in ready_flags
    assert "缺金额" not in ready_flags
    confirm = re.search(
        r'<form class="exp-row-action" method="post" action="/web/review/bulk">.*?</form>',
        ready_flags,
        re.S,
    )
    assert confirm is not None
    confirm_html = confirm.group(0)
    assert 'name="csrf_token"' in confirm_html
    assert 'name="ledger_id" value="owner"' in confirm_html
    assert 'name="filter" value="all"' in confirm_html
    assert re.search(rf'name="expense_snapshot" value="{ready_id}:[^"]+"', confirm_html)
    assert 'name="action" value="confirm_ready"' in confirm_html

    broken_row = re.search(
        rf'<div class="exp-row" data-expense-id="{broken_id}">.*?</a>\s*'
        r'<div class="exp-flags">(.*?)</div>\s*</div>',
        body,
        re.S,
    )
    assert broken_row is not None
    broken_flags = broken_row.group(1)
    assert "缺金额" in broken_flags
    assert "缺商家" not in broken_flags
    assert "疑似重复" not in broken_flags
    assert "exp-row-action" not in broken_flags
    repair = re.search(
        rf'<a class="product-button" href="/web/expenses/{broken_id}/edit\?ledger_id=owner">'
        r"(补全金额|核对重复|补全商家|补全分类|核对汇率)</a>",
        broken_flags,
    )
    assert repair is not None
    assert repair.group(1) == "补全金额"


def test_inbox_pending_viewer_sees_status_without_write_action(
    web_client: TestClient, *, identity
) -> None:
    """K3: viewer 行只见状态 pill — 无勾选、无行内确认表单、无修复链接、
    页头也无上传表单; 批量条依旧不渲染。"""
    expense_id = _create_pending(web_client, identity=identity)
    _demote_owner_ledger_to_viewer()

    body = web_client.get("/web/pending?ledger_id=owner").text
    assert "inbox-upload-form" not in body
    assert 'id="bulk-form"' not in body

    row = re.search(
        rf'<div class="exp-row" data-expense-id="{expense_id}">.*?</a>\s*'
        r'<div class="exp-flags">(.*?)</div>\s*</div>',
        body,
        re.S,
    )
    assert row is not None
    flags = row.group(1)
    assert "缺金额" in flags
    assert "<form" not in flags
    assert "<button" not in flags
    assert "<a " not in flags


def test_retired_inbox_surfaces_and_dashboard_owner_are_gone(
    web_client: TestClient,
) -> None:
    assert web_client.get("/web/tasks").status_code == 404
    assert web_client.get("/web/dashboard/data").status_code == 404

    app_root = Path(__file__).resolve().parents[1] / "app"
    assert not (app_root / "templates" / "web" / "tasks.html").exists()
    assert not (app_root / "templates" / "web" / "dashboard.html").exists()
    assert not (app_root / "static" / "web" / "desktop" / "dashboard.js").exists()


def test_retired_dashboard_runtime_owners_are_physically_gone() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"

    assert not (app_root / "static" / "web" / "pages" / "dashboard.css").exists()
    assert (app_root / "static" / "web" / "components" / "responsive-layout.css").exists()

    desktop_boot = (app_root / "static" / "web" / "desktop.js").read_text(encoding="utf-8")
    assert "initDashboard" not in desktop_boot
    assert "initSparks" not in desktop_boot

    desktop_core = (app_root / "static" / "web" / "desktop" / "core.js").read_text(encoding="utf-8")
    assert "dashboardUrl" not in desktop_core

    insights_css = (
        app_root / "static" / "web" / "product" / "domains" / "insights.css"
    ).read_text(encoding="utf-8")
    assert "data-dashboard-state" not in insights_css

    inbox_css = (
        app_root / "static" / "web" / "product" / "domains" / "inbox.css"
    ).read_text(encoding="utf-8")
    assert ".task-" not in inbox_css

    mutation_ledger = (
        app_root.parent / "scripts" / "_mutate_token_ledger.py"
    ).read_text(encoding="utf-8")
    assert 'POST /web/tasks/{public_id}/cancel' not in mutation_ledger
