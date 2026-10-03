"""One monthly intention survives native editing, cross-client reads and conflicts."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import LedgerMember
from app.routes.web_monthly_arrangement import MonthlyArrangementForm, arrangement_payload
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_budgets import web_client as web_client


def test_web_cross_currency_posts_preserve_report_source_and_save_intent(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from fastapi.testclient import TestClient
    from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
    from sqlalchemy.exc import SQLAlchemyError

    from app.database import get_db
    from app.routes import web_budget_advise as web
    from app.routes import web_monthly_arrangement as save
    from app.schemas._monthly_arrangement import MonthlyArrangementDto
    from app.services.budget_advisor_service import _inputs_builder as builder
    from app.services.budget_advisor_service import _runner
    from app.services.money_projection_service import ProjectionGap
    from tests.test_budget_inputs_projection import seed_reads

    seed_reads(monkeypatch)
    saved = MonthlyArrangementDto(ledger_id="owner", month="2026-08", home_currency_code="JPY",
        savings_target_cents=500, reserved_buffer_cents=100, row_version=3, updated_at=datetime(2026, 9, 27, tzinfo=UTC))
    monkeypatch.setattr(builder, "read_monthly_arrangement", lambda *a, **kw: saved)
    monkeypatch.setattr(builder, "current_calendar", lambda *a, **kw: SimpleNamespace(timezone_name="UTC"))
    monkeypatch.setattr(builder, "now_utc", lambda: datetime(2026, 9, 27, tzinfo=UTC))
    missing = True

    def project(db, **kw):
        assert (kw["source_currency"], kw["home_currency"]) == ("JPY", "USD")
        if missing:
            kw["missing_rates"].add(ProjectionGap("JPY", "USD", date(2026, 8, 31)))
            return None
        return kw["amount_minor"] * 2

    monkeypatch.setattr(builder, "project_recorded_amount", project)
    monkeypatch.setattr(web, "require_runtime_home_currency_code", lambda _: "USD")
    monkeypatch.setattr(builder, "require_runtime_home_currency_code", lambda _: "USD")
    for owner in (web, save):
        monkeypatch.setattr(owner, "_list_ledger_options", lambda _: [])
        monkeypatch.setattr(owner, "_resolve_selected_ledger_id", lambda *a, **kw: "owner")
        monkeypatch.setattr(owner, "preserve_original_ledger_form", lambda *a, **kw: None)
    monkeypatch.setattr(web, "_base_ctx", lambda *a, **kw: {"selected_ledger_id": "owner", "can_write": True})
    monkeypatch.setattr(web, "_advisor_readiness_context", lambda *a, **kw: {
        "provider_name": "local", "provider_enabled": True, "advisor_can_request": True})
    monkeypatch.setattr(web, "_actor_role", lambda *a, **kw: "owner")
    monkeypatch.setattr(web, "_actor_account_id", lambda _: 1)
    monkeypatch.setattr(_runner, "get_advisor_readiness", lambda **_: SimpleNamespace(
        provider="empty", is_live=False, blocked_reason=lambda _: None))
    provider = Mock()
    provider.advise.return_value = None
    monkeypatch.setattr(_runner, "get_budget_advisor", lambda **_: provider)
    monkeypatch.setattr(save, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(save, "resolve_web_actor_account_id", lambda *a: 1)
    monkeypatch.setattr(save, "read_monthly_arrangement", lambda *a, **kw: saved)
    monkeypatch.setattr(save, "review_monthly_arrangement_save", lambda *a, **kw: None)
    command = Mock()
    monkeypatch.setattr(save, "save_monthly_arrangement", command)
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web")]))
    rendered = []

    def render(**kw):
        rendered.append(kw["context"])
        return HTMLResponse(env.get_template(kw["name"]).render(**kw["context"]), status_code=kw.get("status_code", 200))

    monkeypatch.setattr(web, "templates", SimpleNamespace(TemplateResponse=render))
    app = FastAPI()
    app.include_router(web.router)
    app.include_router(save.router, prefix="/web/budget-advise")
    app.dependency_overrides[get_db] = lambda: Mock()
    app.dependency_overrides[web.LocalOnly.dependency] = lambda: None
    client = TestClient(app)
    page = client.get("/web/budget-advise?ledger_id=owner&month=2026-08")
    assert page.status_code == 200
    original_saved = saved
    saved = saved.model_copy(update={"home_currency_code": "USD"})
    no_draft = client.get("/web/budget-advise?ledger_id=owner&month=2026-08&home_currency_code=USD&arrangement_currency_code=JPY")
    untouched = hidden_post_forms(no_draft.text)["/web/budget-advise"]
    assert untouched["arrangement_currency_code"] == "USD"
    assert rendered[-1]["savings_target_yuan"] == "5.00" and rendered[-1]["reserved_buffer_yuan"] == "1.00"
    response = client.post("/web/budget-advise/save", data={**untouched,
        "savings_target_yuan": rendered[-1]["savings_target_yuan"], "reserved_buffer_yuan": rendered[-1]["reserved_buffer_yuan"]},
        follow_redirects=False)
    assert response.status_code == 303
    assert command.call_args.kwargs["payload"].home_currency_code == "USD"
    assert command.call_args.kwargs["payload"].savings_target_cents == 500
    command.reset_mock()
    saved = original_saved
    form = {**hidden_post_forms(page.text)["/web/budget-advise"], "savings_target_yuan": "1200",
        "reserved_buffer_yuan": "30"}
    assert form["home_currency_code"] == "USD" and form["arrangement_currency_code"] == "JPY"
    blocked = client.post("/web/budget-advise", data={**form, "run_advise": "true"})
    assert blocked.status_code == 200 and rendered[-1]["savings_yuan"] is None
    provider.advise.assert_not_called()
    missing = False
    trial = client.post("/web/budget-advise", data=form)
    trial_projection = rendered[-1]
    advice = client.post("/web/budget-advise", data={**form, "run_advise": "true"})
    assert trial.status_code == advice.status_code == 200
    assert rendered[-1]["home_currency_code"] == "USD" and rendered[-1]["savings_yuan"] == "24.00"
    assert rendered[-1]["savings_yuan"] == trial_projection["savings_yuan"]
    assert (provider.advise.call_args.args[0].home_currency, provider.advise.call_args.args[0].savings_target_cents) == ("USD", 2400)
    for error in (AppError("state_conflict", "conflict", status_code=409),
                  AppError("idempotency_key_reused", "key conflict", status_code=409), SQLAlchemyError("unconfirmed")):
        command.side_effect = error
        failed = client.post("/web/budget-advise/save", data=form)
        assert failed.status_code in (409, 503)
        kept = hidden_post_forms(failed.text)["/web/budget-advise"]
        for field in ("home_currency_code", "arrangement_currency_code", "idempotency_key", "expected_row_version"):
            assert kept[field] == form[field]
        assert rendered[-1]["savings_target_yuan"] == "1200" and rendered[-1]["home_currency_code"] == "USD"
    reviewed = client.post("/web/budget-advise/save", data={**form, "review_latest": "true"})
    assert reviewed.status_code == 200 and rendered[-1]["home_currency_code"] == "USD"
    assert hidden_post_forms(reviewed.text)["/web/budget-advise"]["idempotency_key"] == form["idempotency_key"]
    invalid = client.post("/web/budget-advise/save", data={**form, "savings_target_yuan": "oops"})
    assert invalid.status_code == 422 and rendered[-1]["savings_target_yuan"] == "oops"
    assert rendered[-1]["arrangement_currency_input"]["currency_code"] == "JPY" and rendered[-1]["home_currency_code"] == "USD"
    command.side_effect = None
    accepted = client.post("/web/budget-advise/save", data=form, follow_redirects=False)
    assert accepted.status_code == 303
    assert command.call_args.kwargs["payload"].home_currency_code == "JPY"
    assert command.call_args.kwargs["payload"].savings_target_cents == 1200
    assert parse_qs(urlsplit(accepted.headers["location"]).query)["home_currency_code"] == ["USD"]
    assert saved.home_currency_code == "JPY" and saved.savings_target_cents == 500

_MONTH = "2026-09"
_API = f"/api/budget/arrangements/{_MONTH}"


def _open_form(client):
    page = client.get("/web/budget-advise", params={"ledger_id": "owner", "month": _MONTH})
    assert page.status_code == 200, page.text
    return hidden_post_forms(page.text)["/web/budget-advise"]


def _save_first(client):
    form = {**_open_form(client), "savings_target_yuan": "5.00", "reserved_buffer_yuan": "1.00"}
    saved = client.post("/web/budget-advise/save", data=form, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    return form


def test_web_save_is_read_by_api_and_trial_does_not_write(web_client, identity):
    _save_first(web_client)
    stored = web_client.get(_API, headers=identity.app_headers).json()["arrangement"]
    assert (stored["savings_target_cents"], stored["reserved_buffer_cents"], stored["row_version"]) == (500, 100, 1)
    projection = web_client.get("/api/budget/advisor/inputs", params={"month": _MONTH}, headers=identity.app_headers).json()
    assert projection["saved_arrangement"] == stored and not projection["is_trial"]
    assert projection["breakdown"]["shortfall_cents"] == 600
    trial = web_client.post("/web/budget-advise", data={**_open_form(web_client),
        "savings_target_yuan": "9.00", "reserved_buffer_yuan": "1.00"})
    assert trial.status_code == 200, trial.text
    assert "临时试算，尚未保存" in trial.text and "超出计划收入" in trial.text
    assert 'value="9.00"' in trial.text and "¥10.00" in trial.text
    assert web_client.get(_API, headers=identity.app_headers).json()["arrangement"] == stored
    reloaded = web_client.get("/web/budget-advise", params={"ledger_id": "owner", "month": _MONTH})
    assert 'name="savings_target_yuan"' in reloaded.text and 'value="5.00"' in reloaded.text
    history = web_client.get("/web/budget-advise/history", params={"ledger_id": "owner", "month": _MONTH})
    assert history.status_code == 200 and "¥5.00" in history.text and "¥9.00" not in history.text


def test_conflict_review_preserves_original_body_currency_and_key_until_explicit_save(web_client, identity):
    _save_first(web_client)
    draft = {**_open_form(web_client), "savings_target_yuan": "7.00", "reserved_buffer_yuan": "1.00"}
    newer = web_client.put(_API, headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}, json={
        "home_currency_code": "CNY", "savings_target_cents": 600, "reserved_buffer_cents": 200, "expected_row_version": 1})
    assert newer.status_code == 200, newer.text
    refused = web_client.post("/web/budget-advise/save", data=draft)
    assert refused.status_code == 409 and 'value="7.00"' in refused.text
    preserved = hidden_post_forms(refused.text)["/web/budget-advise"]
    assert preserved["idempotency_key"] == draft["idempotency_key"] and preserved["expected_row_version"] == "1"
    review = web_client.post("/web/budget-advise/save", data={**draft, "review_latest": "true"})
    assert review.status_code == 200, review.text
    reviewed = hidden_post_forms(review.text)["/web/budget-advise"]
    assert reviewed["expected_row_version"] == "2" and reviewed["idempotency_key"] == draft["idempotency_key"]
    assert web_client.get(_API, headers=identity.app_headers).json()["arrangement"] == newer.json()
    saved = web_client.post("/web/budget-advise/save", data={**draft, **reviewed}, follow_redirects=False)
    assert saved.status_code == 303
    current = web_client.get(_API, headers=identity.app_headers).json()["arrangement"]
    assert current["savings_target_cents"] == 700 and current["row_version"] == 3


def test_viewer_sees_saved_arrangement_and_history_but_cannot_save(web_client, identity):
    draft = _save_first(web_client)
    with SessionLocal.begin() as db:
        db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner")).role = "viewer"
    page = web_client.get("/web/budget-advise", params={"ledger_id": "owner", "month": _MONTH})
    assert page.status_code == 200 and "已保存第 1 版" in page.text
    assert 'formaction="/web/budget-advise/save"' not in page.text
    assert web_client.post("/web/budget-advise/save", data=draft).status_code == 403
    history = web_client.get("/web/budget-advise/history", params={"ledger_id": "owner", "month": _MONTH})
    assert history.status_code == 200 and "¥5.00" in history.text


def test_captured_zero_decimal_form_does_not_reinterpret_values():
    form = MonthlyArrangementForm(month=_MONTH, home_currency_code="JPY", savings_target_yuan="500",
        reserved_buffer_yuan="0", expected_row_version="null", idempotency_key="original")
    payload = arrangement_payload(form)
    assert payload.savings_target_cents == 500 and payload.reserved_buffer_cents == 0
    assert payload.home_currency_code == "JPY" and payload.expected_row_version is None
    assert form.savings_target_yuan == "500" and form.idempotency_key == "original"


def test_cross_currency_save_keeps_jpy_fact_and_usd_report():
    form = MonthlyArrangementForm(month=_MONTH, home_currency_code="USD", arrangement_currency_code="JPY",
        savings_target_yuan="1200", reserved_buffer_yuan="30", expected_row_version="3", idempotency_key="original")
    payload = arrangement_payload(form)
    assert payload.home_currency_code == "JPY" and payload.savings_target_cents == 1200
    assert payload.reserved_buffer_cents == 30 and payload.expected_row_version == 3
    assert form.home_currency_code == "USD" and form.idempotency_key == "original"


@pytest.mark.parametrize("version", ["", "0", "yesterday"])
def test_missing_version_never_becomes_permission_to_create_a_new_arrangement(version):
    form = MonthlyArrangementForm(home_currency_code="JPY", savings_target_yuan="500", expected_row_version=version)
    with pytest.raises(AppError) as exc:
        arrangement_payload(form)
    assert exc.value.error == "state_conflict" and form.savings_target_yuan == "500"
