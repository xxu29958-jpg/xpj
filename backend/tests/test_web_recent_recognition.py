"""Reopening Pending discovers only this account/ledger's original upload tasks."""

import json
import re
from datetime import UTC, datetime
from html import unescape
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from api_contract_helpers import reject_expense_api
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy import select
from starlette.requests import Request

from app.database import SessionLocal
from app.models import Account, BackgroundTask, Expense
from app.routes import _web_pending_enrichment_watch as recognition
from app.routes.owner_console._shared import templates as owner_templates
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.routes.web_common import templates
from app.services.currency_binding_service import authorize_currency_metadata_write
from tests._web_public_session_support import mint_session, public_client
from tests.test_background_task_continuation import _failed_upload


def _render(engine, name, context):
    env = engine.env.overlay(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), engine.env.loader]))
    return env.get_template(name).render(context)


def _task_fragment(html, public_id):
    marker = f'data-recognition-task-id="{public_id}"'
    assert marker in html, "重开页面无 watch 参数时仍须能辨明原识别任务"
    return html.split(marker, 1)[1].split('data-recognition-task-id="', 1)[0]


def test_reopened_pending_template_shows_failed_and_no_result_original_tasks():
    now = datetime(2026, 9, 27, 2, tzinfo=UTC)
    tasks = [{"public_id": str(uuid4()), "task_type": "expense_enrichment", "status": status,
        "recognition_state": "failed" if status == "failed" else "no_result",
        "recognition_error": "自动识别失败，请打开原单重试识别或手动补全。" if status == "failed" else None,
        "error_message": "本机识别服务不可用" if status == "failed" else None,
        "result_summary": summary, "source_expense_id": source, "created_at": now, "completed_at": now}
        for status, summary, source in (("failed", None, 41), ("completed", {"outcome": "no_result"}, 42))]
    html = _render(templates, "pending.html", {"selected_ledger_id": "owner", "expenses": [],
        "pending_count": 0, "filter": "all", "can_write": False, "recent_recognition_tasks": tasks})
    failed = _task_fragment(html, tasks[0]["public_id"])
    no_result = _task_fragment(html, tasks[1]["public_id"])
    assert "失败" in failed and "重试识别" in failed
    assert "完成" in no_result and ("可用字段" in no_result or "未识别" in no_result or "无结果" in no_result)
    for fragment, source in ((failed, 41), (no_result, 42)):
        assert f'/web/expenses/{source}/edit?ledger_id=owner' in fragment
        assert not re.search(r'<form\b[^>]*method="post"', fragment), "发现任务不能自动重跑旧上传任务"


@pytest.mark.parametrize("page", ["settings/recognition.html", "diagnostics.html"])
def test_owner_recognition_pages_navigate_to_user_pending_context(page):
    context = {"request": Request({"type": "http", "path": "/owner/" + page.removesuffix(".html"), "headers": []}),
        "recognition_view": SimpleNamespace(form=SimpleNamespace(), rapidocr_available=False,
        receipt_status="已配置，自动识别关闭", debt_bill_status="手动录入")}
    html = _render(owner_templates, page, context)
    assert 'href="/web/pending#recognition"' in html, (
        "Owner 只导航到用户待处理业务上下文，不用管理权限代列其他人的识别任务")


@pytest.mark.parametrize("summary", [None, "{broken", "{}", "[]", '{"outcome":"unknown"}', '{"outcome":[]}'])
def test_recent_completed_result_requires_a_validated_outcome(monkeypatch, summary):
    task = BackgroundTask(id=7, public_id=str(uuid4()), tenant_id="owner", task_type="expense_enrichment",
        status="completed", result_summary_json=summary, source_expense_id=None,
        created_at=datetime(2026, 9, 27, 2, tzinfo=UTC), progress_current=0)
    monkeypatch.setattr(recognition, "resolve_web_actor_account_id", lambda *_: 3)
    monkeypatch.setattr(recognition.background_task_service, "list_recent_tasks", lambda *_a, **_k: [task])
    request = Request({"type": "http", "method": "GET", "path": "/web/pending", "headers": [], "query_string": b""})
    context = recognition.web_pending_enrichment_context(object(), request, tenant_id="owner",
        raw_task_public_id=None, flash_message="", flash_type="")
    html = _render(templates, "pending.html", {**context, "selected_ledger_id": "owner",
        "expenses": [], "pending_count": 0, "filter": "all", "can_write": False})
    fragment = _task_fragment(html, task.public_id)
    assert "已完成" not in fragment, "缺失、损坏或未知结果不能被近期记录误报为成功完成"
    assert "失败" in fragment or "无法核对" in fragment
    assert task.status == "completed" and task.result_summary_json == summary, "展示校验不得改写原任务记录"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_reopened_active_task_link_uses_the_existing_watch_consumer(monkeypatch, status):
    task = {"public_id": str(uuid4()), "status": status, "source_expense_id": None,
        "created_at": datetime(2026, 9, 27, 2, tzinfo=UTC)}
    html = _render(templates, "pending.html", {"selected_ledger_id": "owner", "expenses": [],
        "pending_count": 0, "filter": "missing_amount", "can_write": False, "recent_recognition_tasks": [task]})
    fragment = _task_fragment(html, task["public_id"])
    link = re.search(r'href="([^"]+)"[^>]*>\s*查看进度\s*</a>', fragment)
    assert link, "重开页面的处理中任务必须能进入既有进度观察，而非成为静态死记录"
    target = urlsplit(unescape(link.group(1)))
    query = parse_qs(target.query)
    assert target.path == "/web/pending"
    assert query["watch"] == [task["public_id"]] and query["ledger_id"] == ["owner"]
    assert query["filter"] == ["missing_amount"]
    row = SimpleNamespace(task_type="expense_enrichment", status=status, result_summary_json=None)
    monkeypatch.setattr(recognition, "resolve_web_actor_account_id", lambda *_: 3)
    monkeypatch.setattr(recognition.background_task_service, "get_task", lambda *_a, **_k: row)
    monkeypatch.setattr(recognition, "pending_enrichment_watch_timeout_ms", lambda: 30000)
    request = Request({"type": "http", "method": "GET", "path": target.path,
        "headers": [], "query_string": target.query.encode()})
    watch = recognition.resolve_web_pending_enrichment_watch(object(), request,
        tenant_id="owner", raw_task_public_id=query["watch"][0])
    assert watch.state == "pending"
    row.status, row.result_summary_json = "completed", '{"outcome":"no_result"}'
    finished = recognition.resolve_web_pending_enrichment_watch(object(), request,
        tenant_id="owner", raw_task_public_id=query["watch"][0])
    assert finished.state == "no_result", "同一原任务后续完成应由原 watch 消费者观察"


@pytest.mark.parametrize("code, expected", [
    ("OperationalError", "自动识别失败"), ("orphaned_after_restart", "服务重启"),
    ("task_submission_failed", "未能启动"), ("task_input_unavailable", "原识别输入"),
])
def test_recent_failure_explains_recovery_without_rendering_internal_diagnostics(monkeypatch, code, expected):
    diagnostic = "SELECT internal_fixture_secret FROM private_table; C:/private-fixture/input BACKGROUND_TASK_ORPHAN_GRACE_SECONDS"
    task = BackgroundTask(id=7, public_id=str(uuid4()), tenant_id="owner", task_type="expense_enrichment",
        status="failed", error_code=code, error_message=diagnostic, source_expense_id=None,
        created_at=datetime(2026, 9, 27, 2, tzinfo=UTC), progress_current=0)
    monkeypatch.setattr(recognition, "resolve_web_actor_account_id", lambda *_: 3)
    monkeypatch.setattr(recognition.background_task_service, "list_recent_tasks", lambda *_a, **_k: [task])
    request = Request({"type": "http", "method": "GET", "path": "/web/pending", "headers": [], "query_string": b""})
    context = recognition.web_pending_enrichment_context(object(), request, tenant_id="owner",
        raw_task_public_id=None, flash_message="", flash_type="")
    html = _render(templates, "pending.html", {**context, "selected_ledger_id": "owner",
        "expenses": [], "pending_count": 0, "filter": "all", "can_write": False})
    fragment = _task_fragment(html, task.public_id)
    assert "internal_fixture_secret" not in fragment and "BACKGROUND_TASK_ORPHAN_GRACE_SECONDS" not in fragment
    assert expected in fragment and ("重试" in fragment or "重新识别" in fragment)
    assert task.error_code == code and task.error_message == diagnostic, "普通页面投影不能丢弃原诊断记录"


def _snapshot():
    with SessionLocal() as db:
        return {model.__name__: [tuple(getattr(row, c.key) for c in model.__table__.columns)
            for row in db.scalars(select(model).order_by(model.id))]
            for model in (BackgroundTask, Expense)}


def _read_as_current_account(web_client, identity):
    token = mint_session(web_client, identity=identity)
    browser = public_client()
    browser.cookies.set(SESSION_COOKIE_NAME, token, path="/")
    return browser


@pytest.mark.real_db
def test_reopened_http_scopes_recent_upload_tasks_and_does_not_write(web_client, monkeypatch, *, identity):
    failed = _failed_upload(web_client, monkeypatch, identity.app_headers)
    no_result = _failed_upload(web_client, monkeypatch, identity.app_headers)
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == failed["enrichment_task_public_id"]))
        no_result_task = db.scalar(select(BackgroundTask).where(
            BackgroundTask.public_id == no_result["enrichment_task_public_id"]))
        no_result_task.status = "completed"
        no_result_task.error_code = no_result_task.error_message = None
        no_result_task.result_summary_json = json.dumps({"outcome": "no_result"})
        foreign = Account(display_name="另一个账号")
        db.add(foreign)
        db.flush()
        hidden = [BackgroundTask(task_type=kind, tenant_id=ledger, initiated_by_account_id=account,
            status="failed", error_message="不可见任务", source_expense_id=failed["id"])
            for kind, ledger, account in (("expense_enrichment", "owner", foreign.id),
                ("expense_enrichment", "tester_1", task.initiated_by_account_id),
                ("expense_enrichment", None, task.initiated_by_account_id),
                ("expense_fx", "owner", task.initiated_by_account_id))]
        hidden.extend(BackgroundTask(task_type="expense_fx", tenant_id="owner",
            initiated_by_account_id=task.initiated_by_account_id, status="completed") for _ in range(12))
        db.add_all(hidden)
        db.commit()
        hidden_ids = [row.public_id for row in hidden]
    before = _snapshot()
    with _read_as_current_account(web_client, identity) as browser:
        page = browser.get("/web/pending?ledger_id=owner")
    assert page.status_code == 200, page.text
    for receipt in (failed, no_result):
        fragment = _task_fragment(page.text, receipt["enrichment_task_public_id"])
        assert f'/web/expenses/{receipt["id"]}/edit?ledger_id=owner' in fragment
    assert "失败" in _task_fragment(page.text, failed["enrichment_task_public_id"])
    assert "完成" in _task_fragment(page.text, no_result["enrichment_task_public_id"])
    assert all(public_id not in page.text for public_id in hidden_ids)
    assert _snapshot() == before, "发现近期任务只读，不得修改任务或财务事实"


@pytest.mark.real_db
def test_recent_http_tasks_without_valid_original_never_invent_links(web_client, monkeypatch, *, identity):
    original = _failed_upload(web_client, monkeypatch, identity.app_headers)
    foreign = _failed_upload(web_client, monkeypatch, identity.gray_app_headers)
    removed = _failed_upload(web_client, monkeypatch, identity.app_headers)
    rejected = reject_expense_api(web_client, original["id"], headers=identity.app_headers)
    assert rejected.status_code == 200, rejected.text
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        db.delete(db.get(Expense, removed["id"]))
        db.commit()
        removed_task = db.scalar(select(BackgroundTask).where(
            BackgroundTask.public_id == removed["enrichment_task_public_id"]))
        assert removed_task.source_expense_id is None, "真实原单删除应由 FK SET NULL 保留无来源任务"
        owner = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == original["enrichment_task_public_id"]))
        invalid = [BackgroundTask(task_type="expense_enrichment", tenant_id="owner",
            initiated_by_account_id=owner.initiated_by_account_id, status="failed",
            source_expense_id=source, error_message="原单不可用")
            for source in (None, foreign["id"], original["id"])]
        db.add_all(invalid)
        db.commit()
        ids = [row.public_id for row in invalid] + [removed["enrichment_task_public_id"]]
    before = _snapshot()
    with _read_as_current_account(web_client, identity) as browser:
        page = browser.get("/web/pending?ledger_id=owner")
    assert page.status_code == 200, page.text
    for public_id in ids:
        fragment = _task_fragment(page.text, public_id)
        assert not re.search(r'href="/web/expenses/\d+/', fragment)
        assert "原单" in fragment and ("不可" in fragment or "无法" in fragment or "不再" in fragment)
    assert _snapshot() == before
