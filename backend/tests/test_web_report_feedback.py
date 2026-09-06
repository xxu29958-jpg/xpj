"""Actual report return routes and template, with read services isolated from DB."""

import re
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader, StrictUndefined
from markupsafe import escape


@pytest.fixture()
def report_client(monkeypatch):
    from scripts.check_api_contract import _load_app_openapi

    _load_app_openapi()
    from sqlalchemy.engine import Engine

    from app.database import get_db
    from app.errors import AppError
    from app.routes import web_expense_correction, web_expense_edit, web_reports

    def no_database(*_args, **_kwargs):
        pytest.fail("Report return feedback must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_database)
    modules = (web_reports, web_expense_edit, web_expense_correction)
    for module in modules:
        monkeypatch.setattr(module, "_list_ledger_options", lambda _db: [])
        monkeypatch.setattr(module, "_resolve_selected_ledger_id", lambda *_a, **_k: "family")

    def missing_fact(*_args, **_kwargs):
        raise AppError("expense_not_found", status_code=404)

    monkeypatch.setattr(web_expense_edit, "web_edit_context", missing_fact)
    monkeypatch.setattr(web_expense_correction, "get_expense", missing_fact)
    monkeypatch.setattr(web_reports, "require_runtime_home_currency_code", lambda _db: "CNY")
    monkeypatch.setattr(web_reports, "_sidebar_counts", lambda *_a: {})
    monkeypatch.setattr(web_reports, "_monthly_report_sections", lambda *_a, **_k: (None, []))
    monkeypatch.setattr(web_reports, "six_month_summary", lambda *_a, **_k: [])
    monkeypatch.setattr(web_reports, "_top_expenses_view", lambda *_a, **_k: [])
    monkeypatch.setattr(web_reports, "_base_ctx", lambda _request, **kw: {
        "selected_ledger_id": kw["selected_ledger_id"], "home_currency_symbol": "¥",
    })
    monkeypatch.setattr(web_reports, "reports_overview", lambda _db, **kw: kw)
    monkeypatch.setattr(web_reports, "_view_model", lambda payload, **_k: {
        **payload, "merchant_category": "", "total_amount_yuan": "0.00",
        "year_over_year_delta_amount_yuan": "0.00", "count": 0, "previous_count": 0,
        "trend": [], "category_comparison": [], "merchant_ranking": [],
    })
    template_root = Path(__file__).resolve().parents[1] / "app/templates/web"
    monkeypatch.setattr(web_reports.templates.env, "loader", ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(template_root),
    ]))
    monkeypatch.setattr(web_reports.templates.env, "undefined", StrictUndefined)
    web_reports.templates.env.cache.clear()
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[web_reports.LocalOnly.dependency] = lambda: None
    for module in modules:
        app.include_router(module.router)
    client = TestClient(app)
    yield client
    client.close()
    web_reports.templates.env.cache.clear()


@pytest.mark.parametrize("entry", ["edit", "correct"])
def test_unavailable_report_fact_returns_visible_error_in_original_month(report_client, entry):
    response = report_client.get(
        f"/web/expenses/41/{entry}?ledger_id=family&return_to=reports&return_month=2026-05",
    )
    assert len(response.history) == 1
    assert response.history[0].status_code == 303
    target = urlsplit(str(response.url))
    assert target.path == "/web/reports"
    fields = parse_qs(target.query)
    assert fields["ledger_id"] == ["family"] and fields["month"] == ["2026-05"]
    assert fields["flash_type"] == ["error"]
    assert response.status_code == 200
    assert 'role="alert"' in response.text
    assert fields["msg"][0] in response.text


@pytest.mark.parametrize("kind,role", [("error", "alert"), ("untrusted-class", "status")])
def test_report_feedback_is_escaped_and_does_not_spread_to_controls_or_export(report_client, kind, role):
    message = '<script>alert("returned")</script>'
    response = report_client.get("/web/reports", params={
        "ledger_id": "family", "month": "2026-05", "msg": message, "flash_type": kind,
    })
    assert response.status_code == 200
    assert f'role="{role}"' in response.text
    assert str(escape(message)) in response.text and message not in response.text
    assert "untrusted-class" not in response.text
    links = re.findall(r'href="([^"]+)"', response.text)
    assert any("export.csv?" in href for href in links)
    for href in links:
        query = parse_qs(urlsplit(unescape(href)).query)
        assert "msg" not in query and "flash_type" not in query


def _feedback_request(*, platform="web", method="GET"):
    query = urlencode({
        "ledger_id": "family", "month": "2026-05", "page": "2",
        "granularity": "week", "ranking_metric": "count", "merchant_category": "餐饮",
        "msg": "原账本记录已不存在", "flash_type": "error",
    })
    request = Request({
        "type": "http", "scheme": "http", "server": ("testserver", 80),
        "root_path": "", "path": "/web/reports", "method": method,
        "query_string": query.encode(),
        "headers": [(b"referer", f"http://testserver/web/reports?{query}".encode())],
    })
    request.state.web_session_auth = platform != "loopback"
    request.state.web_session_platform = platform
    return request


@pytest.mark.parametrize("platform", ["web", "desktop", "loopback"])
def test_ledger_switch_leaves_old_feedback_and_keeps_report_scope(report_client, monkeypatch, platform):
    from app.routes import web_auth, web_common, web_reports

    request = _feedback_request(platform=platform)
    rendered = web_reports.templates.env.get_template("_ledger_switcher.html").render(
        request=request, selected_ledger_id="family", selected_ledger_name="Family",
        selected_ledger_role="viewer", selected_ledger_is_default=False,
        ledger_options=[SimpleNamespace(ledger_id="other", name="Other", role="viewer", is_default=False)],
        ledger_switch_next_url=web_common._ledger_switch_next_url(request),
        q="?ledger_id=family", csrf_field="", csrf_token="fixture-csrf",
    )
    if platform == "web":
        next_value = unescape(re.search(r'name="next" value="([^"]+)"', rendered).group(1))
        principal = SimpleNamespace(account_id="account", device_id="device")
        monkeypatch.setattr(web_auth, "authenticate_web_session_principal", lambda *_a, **_k: principal)
        switches = []
        monkeypatch.setattr(web_auth, "switch_ledger", lambda _db, **kw: switches.append(kw))
        report_client.app.include_router(web_auth.router)
        response = report_client.post(
            "/web/auth/ledgers", data={"ledger_id": "other", "next": next_value},
            headers={"cookie": "__Host-session=fixture-session"}, follow_redirects=False,
        )
        assert response.status_code == 303
        assert switches == [{
            "principal": principal, "current_token_value": "fixture-session",
            "account_id": "account", "device_id": "device", "target_ledger_id": "other",
        }]
        target = response.headers["location"]
        expected_ledger = {}
    else:
        target = unescape(re.search(r'<a class="row [^"]*"\s+href="([^"]+)"', rendered).group(1))
        expected_ledger = {"ledger_id": ["other"]}
    monkeypatch.setattr(web_reports, "_resolve_selected_ledger_id", lambda *_a, **_k: "other")
    landing = report_client.get(target)
    assert landing.status_code == 200
    assert "原账本记录已不存在" not in landing.text
    assert urlsplit(target).path == "/web/reports"
    assert parse_qs(urlsplit(target).query) == {
        **expected_ledger, "month": ["2026-05"], "page": ["2"], "granularity": ["week"],
        "ranking_metric": ["count"], "merchant_category": ["餐饮"],
    }


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_session_recovery_keeps_target_scope_without_old_feedback(report_client, method):
    from app.middleware.web_session import _session_recovery_target

    target = _session_recovery_target(_feedback_request(method=method))
    assert urlsplit(target).path == "/web/reports"
    assert parse_qs(urlsplit(target).query) == {
        "month": ["2026-05"], "page": ["2"], "granularity": ["week"],
        "ranking_metric": ["count"], "merchant_category": ["餐饮"],
    }
