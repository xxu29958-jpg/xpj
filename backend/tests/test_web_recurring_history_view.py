"""Recurring history leaves native intents intact and distinguishes recorded definitions."""
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.routes._web_recurring_presenter import apply_form_draft, item_view
from app.routes.web_common import templates
from app.services.recurring_service import RecurringAmountAnomaly
from tests._web_native_form_support import hidden_post_forms


def listing_context(status="active", can_write=True):
    request = Request({"type":"http", "headers":[], "scheme":"http", "server":("test",80),
        "path":"/web/recurring", "query_string":f"ledger_id=owner&status={status}&month=2026-05".encode()})
    row = SimpleNamespace(public_id="series-one", merchant_name="原日元计划", home_currency_code="JPY",
        baseline_amount_cents=1200, last_amount_cents=1200, occurrence_count=0, last_seen_at=None,
        next_expected_date=date(2026,5,8), status=status, source="manual", row_version=7)
    item = item_view(row, RecurringAmountAnomaly(), due_date=date(2026,5,8))
    item["current_edit_form"] = None
    ctx = {"request":request, "selected_ledger_id":"owner", "selected_ledger_role":"owner" if can_write else "viewer",
        "home_currency_code":"JPY", "can_write":can_write, "items":[item], "candidates":[], "hero":None,
        "status_filter":status, "suggested_next_date":"2026-06-08", "csrf_field":'<input type="hidden" name="csrf_token" value="original-csrf">'}
    apply_form_draft(ctx, {"public_id":"series-one", "merchant":"原未保存名称", "baseline_amount_yuan":"001200",
        "home_currency_code":"JPY", "next_expected_date":"2026-05-09", "expected_row_version":"7",
        "idempotency_key":"original-key", "review_required":True}, prepare_review=False)
    return ctx


@pytest.mark.parametrize("status", ["active", "paused", "archived"])
@pytest.mark.parametrize("can_write", [False, True])
def test_native_recurring_history_entry_keeps_reader_access_and_original_editor(status, can_write):
    body = templates.get_template("recurring.html").render(**listing_context(status, can_write))
    assert '/web/recurring/series-one/history?ledger_id=owner' in body
    assert 'month=2026-05' in body and f'status={status}' in body
    if can_write:
        assert 'target="_blank" rel="noopener"' in body
        fields = hidden_post_forms(body)["/web/recurring/series-one/edit"]
        assert fields["idempotency_key"] == "original-key" and fields["expected_row_version"] == "7"
        assert fields["csrf_token"] == "original-csrf" and fields["home_currency_code"] == "JPY"
        assert 'name="baseline_amount_yuan"' in body and 'value="001200"' in body
        assert 'value="原未保存名称"' in body
    else:
        assert 'action="/web/recurring/series-one/edit"' not in body


def occurrence_context(recorded=True):
    snapshot = SimpleNamespace(merchant="原日元定义", merchant_key="original", frequency="monthly",
        home_currency_code="JPY", baseline_amount_cents=1200, next_expected_date=date(2026,5,8), status="active", source="manual")
    definition = SimpleNamespace(series_row_version=7, recorded_at=datetime(2026,9,27,tzinfo=UTC), snapshot=snapshot) if recorded else None
    occurrence = SimpleNamespace(period="2026-05", home_currency_code="CNY", state="fulfilled", row_version=2,
        series_row_version=9, expense_id=None, next_due_date="2026-06-08", paid_home_currency_code="JPY", recorded_definition=definition)
    request = Request({"type":"http", "headers":[], "scheme":"http", "server":("test",80), "path":"/web/recurring/series-one/occurrence"})
    return {"request":request, "selected_ledger_id":"owner", "item":SimpleNamespace(public_id="series-one",merchant_name="当前人民币定义"),
        "occurrence":occurrence, "planned_amount":"90.00", "reserved_amount":"0.00", "paid_amount":"1200",
        "recorded_definition_amount":"1200", "can_associate":False, "payments":[], "limited":False,
        "undo_draft_scope":None}


@pytest.mark.parametrize("recorded", [True, False])
def test_occurrence_does_not_present_current_plan_as_the_unknown_original_definition(recorded):
    body = templates.get_template("recurring_occurrence.html").render(**occurrence_context(recorded))
    assert "当前预计" in body and "当前预留" in body
    if recorded:
        assert "本期首次关联所据定义" in body and "原日元定义" in body and "JPY 1200" in body
        assert "不代表该账务月生效" in body and "记录保存时间" in body
        assert 'datetime="2026-09-27T00:00:00Z"' in body
    else:
        assert "首次关联所据定义未记录" in body and "不能用当前定义补作旧计划" in body
        assert "原日元定义" not in body



def test_unrecorded_occurrence_explains_that_no_association_has_been_created():
    ctx = occurrence_context(False)
    ctx["occurrence"].row_version = 0
    body = templates.get_template("recurring_occurrence.html").render(**ctx)
    assert "尚未建立本期关联记录" in body
    assert "原定义与发生时间未知" not in body


@pytest.fixture()
def history_reader(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.middleware.csrf as csrf
    from app.database import get_db
    from app.errors import AppError, add_exception_handlers
    from app.routes import _web_session_common as sessions
    from app.routes import web_recurring as route
    from app.schemas._recurring_history import RecurringItemHistoryResponse

    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"fictional-recurring-render-key")
    entries = [
        {"row_version":8, "change_kind":"archive", "actor_account_id":42, "recorded_at":datetime(2026,9,27,tzinfo=UTC), "snapshot":{
            "merchant":"后来人民币定义", "merchant_key":"later", "frequency":"monthly", "home_currency_code":"CNY",
            "baseline_amount_cents":9000, "next_expected_date":"2026-09-08", "status":"archived", "source":"manual"}},
        {"row_version":7, "change_kind":"baseline", "actor_account_id":None, "recorded_at":datetime(2026,9,26,tzinfo=UTC), "snapshot":{
            "merchant":"原日元定义", "merchant_key":"original", "frequency":"monthly", "home_currency_code":"JPY",
            "baseline_amount_cents":1200, "next_expected_date":"2026-05-08", "status":"active", "source":"manual"}},
    ]
    calls, state = [], {"role":"viewer", "auth":False}
    def options(db):
        return [sessions.LedgerOption("owner", "原账本", state["role"], True, 0, 0),
            sessions.LedgerOption("other", "其他账本", "viewer", False, 0, 0)]
    def reader(db, *, tenant_id, public_id, limit, before_version):
        calls.append((tenant_id, public_id, limit, before_version))
        if tenant_id != "owner":
            raise AppError("recurring_item_not_found", status_code=404)
        items = [row for row in entries if before_version is None or row["row_version"] < before_version]
        return RecurringItemHistoryResponse(ledger_id=tenant_id, public_id=public_id, items=items[:limit],
            next_before_version=items[limit-1]["row_version"] if len(items)>limit else None)
    monkeypatch.setattr(route, "recurring_item_history", reader)
    monkeypatch.setattr(route, "_list_ledger_options", options)
    monkeypatch.setattr(sessions, "list_ledgers_for_account", lambda db, **kw: options(db))
    monkeypatch.setattr(route, "_base_ctx", lambda request, **kw:
        {"request":request, "selected_ledger_id":kw["selected_ledger_id"], "selected_ledger_role":state["role"], "can_write":state["role"]=="owner"})
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(route.router)
    @app.middleware("http")
    async def principal(request, call_next):
        if state["auth"]:
            request.state.web_session_auth = SimpleNamespace(account_id=42, device_id=21, ledger_id="owner", role=state["role"], ledger_name="原账本")
        return await call_next(request)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(rollback=lambda:None)
    app.dependency_overrides[sessions._require_local] = lambda: None
    with TestClient(app) as client:
        yield client, calls, entries, state


def test_recurring_history_real_reader_page_keeps_cursor_filter_and_original_period(history_reader):
    import re
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    client, calls, _, _ = history_reader
    first = client.get("/web/recurring/series-one/history", params={"ledger_id":"owner", "limit":1, "status":"archived", "month":"2026-05", "return_occurrence":"true"})
    assert first.status_code == 200 and "CNY 90.00" in first.text and "已归档" in first.text
    assert 'method="post"' not in first.text
    older = next(unescape(href) for href,label in re.findall(r'href="([^"]+)"[^>]*>([^<]+)</a>',first.text) if label=="更早的记录")
    assert parse_qs(urlsplit(older).query) == {"ledger_id":["owner"], "limit":["1"], "status":["archived"], "month":["2026-05"], "return_occurrence":["true"], "before_version":["8"]}
    second = client.get(older)
    assert second.status_code == 200 and "JPY 1200" in second.text and "原日元定义" in second.text
    assert "2026-05-08" in second.text and "更早的修改及发生时间未知" in second.text
    assert 'datetime="2026-09-26T00:00:00Z"' in second.text
    assert '/web/recurring/series-one/occurrence?ledger_id=owner&amp;month=2026-05' in second.text
    assert "最近的记录</a>" in second.text and "更早的记录</a>" not in second.text
    assert calls == [("owner","series-one",1,None),("owner","series-one",1,8)]
    listing = client.get("/web/recurring/series-one/history",params={"ledger_id":"owner", "status":"archived", "month":"2026-05"})
    assert '/web/recurring?ledger_id=owner&amp;status=archived&amp;month=2026-05#item-series-one' in listing.text


@pytest.mark.parametrize("params", [{"limit":0}, {"limit":101}, {"before_version":0}, {"status":"unknown"}])
def test_recurring_history_invalid_window_never_enters_reader(history_reader, params):
    client, calls, _, _ = history_reader
    assert client.get("/web/recurring/series-one/history", params=params).status_code == 422
    assert calls == []


def test_recurring_history_other_ledger_and_missing_currency_are_not_reconstructed(history_reader):
    client, calls, entries, _ = history_reader
    other = client.get("/web/recurring/series-one/history",params={"ledger_id":"other"})
    assert other.status_code == 404 and "原日元定义" not in other.text
    assert calls == [("other","series-one",20,None)]
    entries[0]["snapshot"]["home_currency_code"] = None
    unknown = client.get("/web/recurring/series-one/history",params={"limit":1})
    assert "9000 最小单位（原币种未记录）" in unknown.text and "CNY 90.00" not in unknown.text
    entries.clear()
    empty = client.get("/web/recurring/series-one/history")
    assert "更早的定义及发生时间未知" in empty.text and '<time datetime=' not in empty.text


@pytest.mark.parametrize("action,owner", [("create","create_manual_recurring_item"), ("edit","update_recurring_item"),
    ("confirm-candidate","confirm_recurring_candidate"), ("pause","pause_recurring_item"),
    ("resume","resume_recurring_item"), ("archive","archive_recurring_item"), ("restore","restore_recurring_item")])
def test_recurring_web_commands_pass_only_the_original_authenticated_actor(history_reader, monkeypatch, action, owner):
    import json

    from app.routes import web_recurring as route
    from app.services import manual_expense_draft_presenter as drafts

    client, _, _, state = history_reader
    state.update(role="owner", auth=True)
    scope = {"datasetId": "installed", "clientGeneration": "generation", "accountId": "42", "deviceId": "21", "ledgerId": "owner"}
    monkeypatch.setattr(drafts, "manual_draft_scope", lambda db, auth: scope)
    captured = []
    monkeypatch.setattr(route, owner, lambda db, **kw: captured.append(kw))
    url = "/web/recurring/" + (action if action in {"create","confirm-candidate"} else "series-one/"+action)
    body = {"ledger_id":"owner", "merchant":"原计划", "baseline_amount_yuan":"1200", "home_currency_code":"JPY",
        "next_expected_date":"2026-05-08", "expected_row_version":"7", "idempotency_key":"original-key",
        "amount_cents":"1200", "actor_account_id":"999", "draft_scope":json.dumps(scope)}
    result = client.post(url,data=body,follow_redirects=False)
    assert result.status_code == 303 and len(captured)==1
    assert captured[0]["tenant_id"] == "owner" and captured[0]["actor_account_id"] == 42
    if action in {"create","edit"}:
        assert captured[0]["idempotency_key"] == "original-key"
    if action in {"edit","pause","resume","restore"}:
        assert captured[0]["expected_row_version"] == 7
    state["role"] = "viewer"
    assert client.post(url,data=body,follow_redirects=False).status_code == 403 and len(captured)==1


def test_occurrence_presenter_formats_recorded_and_current_amounts_with_their_own_currency():
    from app.routes.web_recurring_occurrences import _occurrence_page_projection

    ctx = occurrence_context(True)
    occurrence = ctx["occurrence"]
    occurrence.planned_amount_cents, occurrence.reserved_amount_cents, occurrence.paid_amount_cents = 9000, 0, 1200
    projected = _occurrence_page_projection(item=ctx["item"], occurrence=occurrence, payments=[], focused=None, selected="owner", can_write=False)
    assert projected["recorded_definition_amount"] == "1200"
    assert projected["planned_amount"] == "90.00" and projected["reserved_amount"] == "0.00"
    occurrence.recorded_definition.snapshot.home_currency_code = None
    projected = _occurrence_page_projection(item=ctx["item"], occurrence=occurrence, payments=[], focused=None, selected="owner", can_write=False)
    assert projected["recorded_definition_amount"] == "1200 最小单位（原币种未记录）"
