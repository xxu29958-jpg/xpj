"""Original goal amounts and submission identity survive currency refusals."""

import pytest

from tests._web_native_form_support import hidden_post_forms, open_creation_form
from tests.test_web_goal_edit_continuity import _editor, _goal


def test_jpy_goal_editor_uses_recorded_units_under_cny_runtime(web_client, identity):
    runtime = web_client.get("/api/system/runtime-compatibility", headers=identity.app_headers).json()
    assert runtime["capabilities"]["currency"]["home_currency_code"] == "CNY"
    goal = _goal(web_client, identity, home_currency_code="JPY", amount_minor=1200)
    action, fields = _editor(web_client, goal["public_id"])
    assert fields["home_currency_code"] == "JPY"
    editor = web_client.get(action, params={"ledger_id": "owner"})
    assert 'name="target_amount_yuan" value="1200"' in editor.text
    assert "目标金额（JPY，仅支持整数）" in editor.text
    listing = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert "剩余额度 · JPY" in listing.text and "目标 1200 · 已用 0" in listing.text
    fields.update(name="日元目标调整", month="2026-05", category="餐饮", target_amount_yuan="1500")
    saved = web_client.post(action, data=fields, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    canonical = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert canonical["home_currency_code"] == "JPY"
    assert canonical["target_amount_cents"] == 1500
    assert canonical["row_version"] == goal["row_version"] + 1


@pytest.mark.parametrize(("submitted_currency", "status"), [("", 422), ("JPY", 409)])
def test_goal_edit_currency_refusal_keeps_raw_amount_key_and_occ(
    web_client, identity, submitted_currency, status,
):
    goal = _goal(web_client, identity)
    action, fields = _editor(web_client, goal["public_id"])
    fields.update(name="尚未保存的输入", month="2026-05", category="交通",
        target_amount_yuan="001200", home_currency_code=submitted_currency)
    refused = web_client.post(action, data=fields)
    assert refused.status_code == status, refused.text
    assert 'name="target_amount_yuan" value="001200"' in refused.text
    assert 'name="name" value="尚未保存的输入"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    for key in ("home_currency_code", "idempotency_key", "expected_row_version", "ledger_id"):
        assert retained[key] == fields[key]
    assert ">保存修改</button>" not in refused.text
    assert "在新窗口打开当前目标" in refused.text
    reviewed = web_client.post(action, data={**fields, "review_latest": "true"})
    assert reviewed.status_code == 200
    reviewed_fields = hidden_post_forms(reviewed.text)[action]
    # CSRF is a fresh transport token; original command identity must stay fixed.
    assert {key: value for key, value in reviewed_fields.items() if key != "csrf_token"} == {
        key: value for key, value in retained.items() if key != "csrf_token"
    }
    unchanged = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert unchanged == goal


def test_goal_create_without_currency_keeps_original_form_and_creates_nothing(web_client, identity):
    action = "/web/goals/create"
    page = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert page.status_code == 200
    page = open_creation_form(web_client, page, "new_goal")
    fields = hidden_post_forms(page.text)[action]
    assert fields["home_currency_code"] == "CNY" and fields["idempotency_key"]
    fields.pop("home_currency_code")
    fields.update(name="尚未发送的目标", category="交通", target_amount_yuan="001200.00")
    refused = web_client.post(action, data=fields)
    assert refused.status_code == 422, refused.text
    assert 'name="target_amount_yuan" value="001200.00"' in refused.text
    assert 'name="name" value="尚未发送的目标"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    assert retained["home_currency_code"] == ""
    for key in ("idempotency_key", "month", "ledger_id"):
        assert retained[key] == fields[key]
    assert ">保存目标</button>" not in refused.text
    current = web_client.get("/api/goals?month=2026-05", headers=identity.app_headers)
    assert current.status_code == 200 and current.json()["items"] == []


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("can_write", [False, True])
def test_saved_goal_history_is_readable_beside_a_separate_creation_task(archived, can_write):
    from starlette.requests import Request

    from app.routes.web_common import templates

    request = Request({"type": "http", "headers": [], "scheme": "http", "server": ("test", 80), "path": "/web/goals"})
    goal = {"public_id":"goal-one", "name":"日元目标", "category":"交通", "month":"2026-05", "home_currency_code":"JPY",
        "is_archived":archived, "is_over_limit":False, "target_yuan":"1200", "spent_yuan":"0", "remaining_yuan":"1200",
        "progress_percent":None, "bar_percent":0}
    values = {"month":"2026-05", "name":"原输入", "category":"交通", "target_amount_yuan":"001200", "home_currency_code":"JPY", "idempotency_key":"original-key"}
    body = templates.get_template("goals.html").render(request=request, goals=[goal], month="2026-05",
        include_archived=True, can_write=can_write, selected_ledger_id="owner", values=values,
        form_currency={"currency_code":"JPY", "amount_input_hint":"仅支持整数"})
    assert '/web/goals/goal-one/history?ledger_id=owner' in body
    assert 'month=2026-05' in body and 'include_archived=true' in body
    assert 'action="/web/goals/create"' not in body
    if can_write:
        assert 'new_goal=1' in body
        editor = templates.get_template("goals.html").render(request=request, goals=[], month="2026-05",
            include_archived=True, goal_creating=True, can_write=True, selected_ledger_id="owner", values=values,
            form_currency={"currency_code":"JPY", "amount_input_hint":"仅支持整数"})
        fields = hidden_post_forms(editor)["/web/goals/create"]
        assert fields["idempotency_key"] == "original-key" and fields["home_currency_code"] == "JPY"
        assert 'name="target_amount_yuan" value="001200"' in editor
    else:
        assert 'new_goal=1' not in body


@pytest.fixture()
def history_reader(monkeypatch):
    from datetime import UTC, datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.middleware.csrf as csrf
    from app.database import get_db
    from app.errors import AppError, add_exception_handlers
    from app.routes import web_goals as route
    from app.routes._web_session_common import LedgerOption, _require_local
    from app.schemas._goal_history import GoalHistoryResponse

    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"fictional-render-test-secret")
    entries = [
        {"row_version":8, "change_kind":"archive", "recorded_at":datetime(2026, 9, 27, tzinfo=UTC), "snapshot":{
            "name":"已归档目标", "goal_type":"spending_limit", "period":"monthly", "month":"2026-06", "category":"餐饮",
            "target_amount_cents":1800, "home_currency_code":"JPY", "status":"archived"}},
        {"row_version":7, "change_kind":"baseline", "recorded_at":datetime(2026, 9, 26, tzinfo=UTC), "snapshot":{
            "name":"原交通目标", "goal_type":"spending_limit", "period":"monthly", "month":"2026-05", "category":"交通",
            "target_amount_cents":1200, "home_currency_code":"JPY", "status":"active"}},
    ]
    calls = []
    def reader(db, *, tenant_id, public_id, limit, before_version):
        calls.append((tenant_id, public_id, limit, before_version))
        if tenant_id != "owner":
            raise AppError("goal_not_found", status_code=404)
        items = [row for row in entries if before_version is None or row["row_version"] < before_version]
        return GoalHistoryResponse(ledger_id=tenant_id, public_id=public_id, items=items[:limit],
            next_before_version=items[limit-1]["row_version"] if len(items) > limit else None)
    monkeypatch.setattr(route, "goal_history", reader)
    monkeypatch.setattr(route, "_list_ledger_options", lambda db: [
        LedgerOption("owner", "原账本", "viewer", True, 0, 0), LedgerOption("tester_1", "其他账本", "viewer", False, 0, 0)])
    monkeypatch.setattr(route, "_base_ctx", lambda request, **kw:
        {"request":request, "selected_ledger_id":kw["selected_ledger_id"], "can_write":False, "selected_ledger_role":"viewer"})
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(route.router)
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[_require_local] = lambda: None
    with TestClient(app) as client:
        yield client, calls, entries


def test_goal_history_real_request_preserves_cursor_period_and_original_definition(history_reader):
    import re
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    client, calls, _ = history_reader
    first = client.get("/web/goals/goal-one/history", params={"ledger_id":"owner", "limit":1, "month":"2026-06", "include_archived":"true"})
    assert first.status_code == 200
    assert "已归档目标" in first.text and "JPY" in first.text and "1800" in first.text
    assert '<progress' not in first.text and 'method="post"' not in first.text
    older = next(unescape(href) for href, text in re.findall(r'href="([^"]+)"[^>]*>([^<]+)</a>', first.text) if text == "更早的记录")
    params = parse_qs(urlsplit(older).query)
    assert params == {"ledger_id":["owner"], "limit":["1"], "before_version":["8"], "month":["2026-06"], "include_archived":["true"]}
    second = client.get(older)
    assert second.status_code == 200 and "原交通目标" in second.text and "1200" in second.text
    assert "更早的修改及发生时间未知" in second.text and "记录保存时间" in second.text
    assert 'datetime="2026-09-26T00:00:00Z"' in second.text
    assert "更早的记录</a>" not in second.text and "最近的记录</a>" in second.text
    assert '/web/goals?ledger_id=owner&amp;month=2026-06&amp;include_archived=true#goal-goal-one' in second.text
    assert '/web/goals?ledger_id=owner&amp;month=2026-05&amp;include_archived=true' in second.text
    assert calls == [("owner", "goal-one", 1, None), ("owner", "goal-one", 1, 8)]


@pytest.mark.parametrize("params", [{"limit":0}, {"limit":101}, {"before_version":0}])
def test_goal_history_request_rejects_invalid_pagination_before_reader(history_reader, params):
    client, calls, _ = history_reader
    assert client.get("/web/goals/goal-one/history", params=params).status_code == 422
    assert calls == []


def test_goal_history_other_ledger_cannot_show_original_definition(history_reader):
    client, calls, _ = history_reader
    other = client.get("/web/goals/goal-one/history", params={"ledger_id":"tester_1"})
    assert other.status_code == 404 and "原交通目标" not in other.text
    assert calls == [("tester_1", "goal-one", 20, None)]
    unknown = client.get("/web/goals/goal-one/history", params={"ledger_id":"unknown"})
    assert unknown.status_code == 400 and len(calls) == 1


def test_goal_history_missing_recorded_currency_does_not_use_runtime_currency(history_reader):
    client, _, entries = history_reader
    entries[0]["snapshot"]["home_currency_code"] = None
    page = client.get("/web/goals/goal-one/history", params={"limit":1})
    assert page.status_code == 200 and "1800 最小单位（原币种未记录）" in page.text
    assert "CNY" not in page.text and "¥18.00" not in page.text



def test_goal_editor_history_opens_separately_and_preserves_original_submission():
    from starlette.requests import Request

    from app.routes.web_common import templates

    request = Request({"type":"http", "headers":[], "scheme":"http", "server":("test",80), "path":"/web/goals/goal-one/edit"})
    values = {"name":"尚未保存的原输入", "month":"2026-05", "category":"交通", "target_amount_yuan":"001200",
        "home_currency_code":"JPY", "expected_row_version":"7", "idempotency_key":"original-key"}
    body = templates.get_template("goal_edit.html").render(request=request,
        selected_ledger_id="owner", goal={"public_id":"goal-one", "status":"active"},
        current=values, values=values, currency_matches=True, form_currency={"currency_code":"JPY"})
    assert 'target="_blank" rel="noopener" href="/web/goals/goal-one/history?' in body
    fields = hidden_post_forms(body)["/web/goals/goal-one/edit"]
    for name in ("ledger_id", "expected_row_version", "idempotency_key", "home_currency_code"):
        assert fields[name] == ({"ledger_id":"owner", **values})[name]
    assert 'name="name" value="尚未保存的原输入"' in body
    assert 'name="target_amount_yuan" value="001200"' in body


def test_goal_history_without_known_records_explains_the_gap(history_reader):
    client, _, entries = history_reader
    entries.clear()
    response = client.get("/web/goals/goal-one/history", params={"month":"2026-05"})
    assert response.status_code == 200 and "更早的修改及发生时间未知" in response.text
    assert '<time datetime=' not in response.text and "更早的记录</a>" not in response.text
