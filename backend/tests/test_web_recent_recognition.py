"""Reopening Pending discovers only this account/ledger's original upload tasks."""

import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api_contract_helpers import reject_expense_api
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, BackgroundTask, Expense
from app.routes.owner_console._shared import templates as owner_templates
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.routes.web_common import templates
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
        "error_message": "本机识别服务不可用" if status == "failed" else None,
        "result_summary": summary, "source_expense_id": source, "created_at": now, "completed_at": now}
        for status, summary, source in (("failed", None, 41), ("completed", {"outcome": "no_result"}, 42))]
    html = _render(templates, "pending.html", {"selected_ledger_id": "owner", "expenses": [],
        "pending_count": 0, "filter": "all", "can_write": False, "recent_recognition_tasks": tasks})
    failed = _task_fragment(html, tasks[0]["public_id"])
    no_result = _task_fragment(html, tasks[1]["public_id"])
    assert "失败" in failed and "本机识别服务不可用" in failed
    assert "完成" in no_result and ("可用字段" in no_result or "未识别" in no_result or "无结果" in no_result)
    for fragment, source in ((failed, 41), (no_result, 42)):
        assert f'/web/expenses/{source}/edit?ledger_id=owner' in fragment
        assert not re.search(r'<form\b[^>]*method="post"', fragment), "发现任务不能自动重跑旧上传任务"


@pytest.mark.parametrize("page", ["settings/recognition.html", "diagnostics.html"])
def test_owner_recognition_pages_navigate_to_user_pending_context(page):
    context = {"recognition_view": SimpleNamespace(form=SimpleNamespace(), rapidocr_available=False,
        receipt_status="已配置，自动识别关闭", debt_bill_status="手动录入")}
    html = _render(owner_templates, page, context)
    assert 'href="/web/pending#recognition"' in html, (
        "Owner 只导航到用户待处理业务上下文，不用管理权限代列其他人的识别任务")


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
    rejected = reject_expense_api(web_client, original["id"], headers=identity.app_headers)
    assert rejected.status_code == 200, rejected.text
    with SessionLocal() as db:
        owner = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == original["enrichment_task_public_id"]))
        invalid = [BackgroundTask(task_type="expense_enrichment", tenant_id="owner",
            initiated_by_account_id=owner.initiated_by_account_id, status="failed",
            source_expense_id=source, error_message="原单不可用")
            for source in (None, 99999999, foreign["id"], original["id"])]
        db.add_all(invalid)
        db.commit()
        ids = [row.public_id for row in invalid]
    before = _snapshot()
    with _read_as_current_account(web_client, identity) as browser:
        page = browser.get("/web/pending?ledger_id=owner")
    assert page.status_code == 200, page.text
    for public_id in ids:
        fragment = _task_fragment(page.text, public_id)
        assert not re.search(r'href="/web/expenses/\d+/', fragment)
        assert "原单" in fragment and ("不可" in fragment or "无法" in fragment or "不再" in fragment)
    assert _snapshot() == before
