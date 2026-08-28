from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from _web_bulk_test_support import create_pending as _create_pending
from _web_bulk_test_support import seed_pending_with_amount as _seed_pending_with_amount
from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.routes.uploads as upload_routes
import app.routes.web_inbox_capture as web_inbox_capture_routes
from app.database import SessionLocal
from app.main import app as fastapi_app
from app.models import BackgroundTask, Expense, LedgerMember
from app.routes._upload_request import handle_upload
from app.services.ledger_service import find_owner_account_id_for_ledger
from app.services.ocr_service import OcrExtraction, OcrResult
from tests._infra.assets import PNG_BYTES


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


@pytest.mark.real_db
def test_web_pending_upload_uses_shared_owner_and_creates_real_pending_expense(
    web_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    assert upload_routes.handle_upload is handle_upload
    assert web_inbox_capture_routes.handle_upload is handle_upload

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner&timezone=Asia%2FShanghai",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/web/pending?")
    assert "ledger_id=owner" in response.headers["location"]
    redirect_query = parse_qs(urlsplit(response.headers["location"]).query)

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
        task_public_id = redirect_query["watch"][0]
        assert str(UUID(task_public_id)) == task_public_id
        assert "watch_rv" not in redirect_query
        task = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert task is not None
        assert task.task_type == "expense_enrichment"
        assert task.tenant_id == "owner"
        assert task.status == "completed"
        assert json.loads(task.result_summary_json or "{}")["outcome"] == "no_result"

    final_page = web_client.get(response.headers["location"])
    assert final_page.status_code == 200
    assert "data-inbox-enrichment-terminal" in final_page.text
    assert 'data-enrichment-state="no_result"' in final_page.text
    assert "未返回可用字段" in final_page.text


def test_web_pending_upload_rejects_viewer_before_saving(
    web_client: TestClient,
) -> None:
    _demote_owner_ledger_to_viewer()

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner&timezone=Asia%2FShanghai",
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


@pytest.mark.real_db
def test_web_pending_upload_keeps_saved_row_visible_when_task_submit_fails(
    web_client: TestClient,
    monkeypatch,
) -> None:
    from app.services import background_task_service

    def fail_submit(*_args, **_kwargs):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(background_task_service, "_submit_task", fail_submit)

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    redirect_query = parse_qs(urlsplit(response.headers["location"]).query)
    task_public_id = redirect_query["watch"][0]
    with SessionLocal() as db:
        task = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert task is not None
        assert task.status == "failed"
        assert task.error_code == "task_submission_failed"
        expense = db.scalar(
            select(Expense)
            .where(
                Expense.tenant_id == "owner",
                Expense.source == "网页上传",
            )
            .order_by(Expense.id.desc())
            .limit(1)
        )
        assert expense is not None
        assert expense.status == "pending"

    page = web_client.get(response.headers["location"])
    assert page.status_code == 200
    assert 'data-enrichment-state="failed"' in page.text
    assert "自动识别失败，账单仍安全保留" in page.text


def test_web_pending_upload_rejects_viewer_before_multipart_parse(
    web_client: TestClient,
) -> None:
    _demote_owner_ledger_to_viewer()

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner",
        headers={"Content-Type": "multipart/form-data; boundary=ticketbox"},
        content=b"not-a-valid-multipart-body",
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"


def test_web_pending_upload_applies_shared_multipart_file_count_limit(
    web_client: TestClient,
) -> None:
    files = [
        (field, (f"{field}.png", PNG_BYTES, "image/png"))
        for field in ("file", "image", "photo", "screenshot", "extra")
    ]

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner",
        files=files,
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"


def test_web_pending_upload_openapi_keeps_explicit_multipart_contract() -> None:
    operation = fastapi_app.openapi()["paths"]["/web/pending/upload"]["post"]
    multipart = operation["requestBody"]["content"]["multipart/form-data"]["schema"]

    assert operation["requestBody"]["required"] is True
    assert multipart["required"] == ["file", "csrf_token"]
    assert multipart["properties"]["file"] == {
        "type": "string",
        "format": "binary",
    }
    assert multipart["properties"]["csrf_token"]["type"] == "string"


def test_inbox_pending_header_has_native_upload_form_and_flat_queue_summary(
    web_client: TestClient, *, identity
) -> None:
    """K3: 页头给 writer 原生无 JS 上传表单 (multipart → /web/pending/upload,
    ledger 在 query、csrf 在 body，时区仅作渐进增强；accept=image/* required),
    导入与导出保留为次级入口; 三数字概况墙压平为一句队列小结, 可行动计数
    只留在筛选 pill 上。"""
    _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    response = web_client.get("/web/pending?ledger_id=owner")

    assert response.status_code == 200
    body = response.text
    form = re.search(
        r'<form class="inbox-upload-form" method="post"'
        r' action="/web/pending/upload\?ledger_id=owner" data-inbox-capture'
        r' enctype="multipart/form-data">.*?</form>',
        body,
        re.S,
    )
    assert form is not None
    form_html = form.group(0)
    assert 'name="csrf_token"' in form_html
    assert 'name="ledger_id"' not in form_html
    assert 'name="timezone"' not in form_html
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
    assert "data-inbox-capture" in core_js
    assert 'searchParams.set("timezone", tz)' in core_js
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


def test_inbox_duplicate_action_targets_the_real_review_case(
    web_client: TestClient, *, identity
) -> None:
    _seed_pending_with_amount(web_client, "9.00", "盒马", identity=identity)
    duplicate_id = _seed_pending_with_amount(
        web_client,
        "9.00",
        "盒马",
        identity=identity,
    )

    pending_body = web_client.get("/web/pending?ledger_id=owner").text
    duplicate_row = re.search(
        rf'<div class="exp-row" data-expense-id="{duplicate_id}">.*?'
        r'<div class="exp-flags">(.*?)</div>\s*</div>',
        pending_body,
        re.S,
    )
    assert duplicate_row is not None
    assert (
        f'href="/web/duplicates?ledger_id=owner#duplicate-{duplicate_id}">核对重复</a>'
        in duplicate_row.group(1)
    )

    review_body = web_client.get("/web/duplicates?ledger_id=owner").text
    assert f'id="duplicate-{duplicate_id}"' in review_body


def test_pending_watch_is_task_scoped_and_ignores_unrelated_expense_edits(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    with SessionLocal() as db:
        account_id = find_owner_account_id_for_ledger(db, ledger_id="owner")
        assert account_id is not None
        task = BackgroundTask(
            task_type="expense_enrichment",
            tenant_id="owner",
            initiated_by_account_id=account_id,
            status="queued",
            progress_total=1,
        )
        db.add(task)
        db.commit()
        task_public_id = task.public_id

    watch_url = f"/web/pending?ledger_id=owner&watch={task_public_id}"
    processing = web_client.get(watch_url)
    assert processing.status_code == 200
    assert "data-inbox-enrichment-watch" in processing.text
    assert "正在识别" in processing.text
    timeout = re.search(r'data-watch-timeout-ms="(\d+)"', processing.text)
    assert timeout is not None
    assert int(timeout.group(1)) > 12_000

    updated = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": "19.90",
            "merchant": "盒马",
            "category": "餐饮",
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert updated.status_code == 303, updated.text

    still_processing = web_client.get(watch_url)
    assert still_processing.status_code == 200
    assert "data-inbox-enrichment-watch" in still_processing.text
    assert "data-inbox-enrichment-terminal" not in still_processing.text

    with SessionLocal() as db:
        malformed = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert malformed is not None
        malformed.status = "completed"
        malformed.result_summary_json = "{}"
        db.commit()

    malformed_page = web_client.get(watch_url)
    assert 'data-enrichment-state="failed"' in malformed_page.text
    assert "自动识别失败，账单仍安全保留" in malformed_page.text

    with SessionLocal() as db:
        conflict = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert conflict is not None
        conflict.result_summary_json = json.dumps({"outcome": "conflict"})
        db.commit()

    conflict_page = web_client.get(watch_url)
    assert 'data-enrichment-state="conflict"' in conflict_page.text
    assert "你后来保存的修改已保留" in conflict_page.text

    static_root = Path(__file__).resolve().parents[1] / "app" / "static" / "web"
    core_js = (static_root / "desktop" / "core.js").read_text(encoding="utf-8")
    assert "maxAttempts = 8" not in core_js
    assert "AbortController" in core_js


@pytest.mark.real_db
def test_web_upload_enrichment_task_presents_real_ocr_success(
    web_client: TestClient,
    monkeypatch,
) -> None:
    import app.services.expense_service._create as create_service

    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    monkeypatch.setattr(
        create_service,
        "collect_auto_ocr_extractions",
        lambda *_args, **_kwargs: [
            OcrExtraction(
                provider_name="mock",
                ocr_model="test-model",
                result=OcrResult(
                    raw_text="盒马\n交易金额：19.90",
                    confidence=0.98,
                    amount_cents=1990,
                    merchant="盒马",
                ),
            )
        ],
    )

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner&timezone=Asia%2FShanghai",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    page = web_client.get(response.headers["location"])
    assert page.status_code == 200
    assert "data-inbox-enrichment-watch" not in page.text
    assert 'data-enrichment-state="updated"' in page.text
    assert "识别结果已更新，请核对后确认" in page.text

    task_public_id = parse_qs(urlsplit(response.headers["location"]).query)["watch"][0]
    with SessionLocal() as db:
        task = db.scalar(
            select(BackgroundTask).where(BackgroundTask.public_id == task_public_id)
        )
        assert task is not None
        assert task.status == "completed"
        result = json.loads(task.result_summary_json or "{}")
        assert result["outcome"] == "updated"
        expense = db.get(Expense, result["expense_id"])
        assert expense is not None
        assert expense.amount_cents == 1990
        assert expense.merchant == "盒马"


@pytest.mark.real_db
def test_web_upload_enrichment_task_presents_provider_failure(
    web_client: TestClient,
    monkeypatch,
) -> None:
    import app.services.expense_service._create as create_service

    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")

    def fail_ocr(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(create_service, "collect_auto_ocr_extractions", fail_ocr)

    response = web_client.post(
        "/web/pending/upload?ledger_id=owner",
        files={"file": ("receipt.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text

    page = web_client.get(response.headers["location"])
    assert page.status_code == 200
    assert "data-inbox-enrichment-watch" not in page.text
    assert 'data-enrichment-state="failed"' in page.text
    assert "自动识别失败，账单仍安全保留" in page.text


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
