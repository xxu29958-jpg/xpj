"""Native manual rates return to the captured budget task without paid generation."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from starlette.templating import Jinja2Templates

from app.database import get_db
from app.errors import AppError
from app.routes import web_budget_fx


@pytest.fixture
def task(monkeypatch):
    db = Mock()
    monkeypatch.setattr(web_budget_fx, "_list_ledger_options", lambda _: [])
    monkeypatch.setattr(web_budget_fx, "_resolve_selected_ledger_id", lambda *a, **k: "original")
    monkeypatch.setattr(web_budget_fx, "_require_selected_ledger_write", lambda *a: None)
    monkeypatch.setattr(web_budget_fx, "resolve_web_actor_account_id", lambda *a: 7)
    monkeypatch.setattr(web_budget_fx, "preserve_original_ledger_form", lambda *a, **k: None)
    monkeypatch.setattr(web_budget_fx, "_base_ctx", lambda *a, **k: {"can_write": True})
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader(Path(__file__).parents[1] / "app/templates/web"),
    ]))
    monkeypatch.setattr(web_budget_fx, "templates", Jinja2Templates(env=env))
    monkeypatch.setattr(web_budget_fx, "list_exchange_rates", Mock(return_value=[]))
    saved = Mock(return_value=SimpleNamespace(currency_code="CNY", home_currency_code="JPY", rate_date=date(2026, 8, 5)))
    returned = Mock(return_value=HTMLResponse("original budget"))
    monkeypatch.setattr(web_budget_fx, "set_exchange_rate_idempotently", saved)
    monkeypatch.setattr(web_budget_fx, "_render_budget_advise", returned)
    # Render the real editor while retaining the isolated actor/database fixture.
    app = FastAPI()
    app.include_router(web_budget_fx.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[web_budget_fx.LocalOnly.dependency] = lambda: None
    return SimpleNamespace(client=TestClient(app), saved=saved, returned=returned, db=db)


def _form(**changes):
    result = {"ledger_id": "original", "month": "2026-08", "home_currency_code": "JPY",
        "savings_target_yuan": "12", "reserved_buffer_yuan": "3", "currency_code": "CNY",
        "rate_date": "2026-08-05", "rate_to_cny": "20.125", "expected_row_version": "2",
        "idempotency_key": "original-rate-command"}
    return {**result, **changes}


def test_save_uses_same_owner_and_returns_original_task_without_generation(task):
    response = task.client.post("/web/budget-advise/rates", data=_form())
    assert response.status_code == 200, response.text
    args = task.saved.call_args.kwargs
    assert (args["tenant_id"], args["actor_account_id"], args["idempotency_key"]) == ("original", 7, "original-rate-command")
    payload = args["payload"]
    assert (payload.currency_code, payload.home_currency_code, payload.rate_date, payload.expected_row_version) == (
        "CNY", "JPY", date(2026, 8, 5), 2)
    assert str(payload.rate_to_cny) == "20.125"
    returned = task.returned.call_args.kwargs
    assert returned["month"] == "2026-08" and returned["home_currency_code"] == "JPY"
    assert returned["savings_target_yuan"] == "12" and returned["reserved_buffer_yuan"] == "3"
    assert returned["run_advise"] is returned["allow_outbound"] is False


@pytest.mark.parametrize("error", ["state_conflict", "idempotency_key_reused"])
def test_conflict_retains_raw_rate_key_version_and_original_month(task, error):
    task.saved.side_effect = AppError(error, status_code=409)
    response = task.client.post("/web/budget-advise/rates", data=_form())
    assert response.status_code == 409, response.text
    for name, value in _form().items():
        assert f'name="{name}"' in response.text and f'value="{value}"' in response.text
    assert "核对当前汇率" in response.text
    task.returned.assert_not_called()
    task.db.rollback.assert_called_once()


def test_invalid_rate_stays_editable_without_command(task):
    response = task.client.post("/web/budget-advise/rates", data=_form(rate_to_cny="not a rate"))
    assert response.status_code == 422, response.text
    assert 'value="not a rate"' in response.text and 'type="text"' in response.text
    task.saved.assert_not_called()


def test_explicit_review_reads_current_version_but_does_not_submit(task, monkeypatch):
    current = SimpleNamespace(currency_code="CNY", home_currency_code="JPY", rate_date=date(2026, 8, 5),
        rate_to_cny="21", row_version=8)
    monkeypatch.setattr(web_budget_fx, "list_exchange_rates", Mock(return_value=[current]))
    response = task.client.post("/web/budget-advise/rates", data=_form(review_latest="true"))
    assert response.status_code == 200, response.text
    assert 'name="expected_row_version" value="8"' in response.text
    assert 'name="rate_to_cny" value="20.125"' in response.text
    assert 'value="2026-08"' in response.text
    assert 'value="original-rate-command"' not in response.text
    task.saved.assert_not_called()


def test_existing_rate_editor_keeps_the_reviewed_pair_and_date_fixed(task, monkeypatch):
    current = SimpleNamespace(currency_code="CNY", home_currency_code="JPY", rate_date=date(2026, 8, 5),
        rate_to_cny="21", row_version=2)
    monkeypatch.setattr(web_budget_fx, "list_exchange_rates", Mock(return_value=[current]))
    response = task.client.get("/web/budget-advise/rates", params=_form())
    assert response.status_code == 200, response.text
    editor = response.text.split('<form method="post"', 1)[1].split('</form>', 1)[0]
    assert 'type="hidden" name="currency_code" value="CNY"' in editor
    assert 'type="hidden" name="rate_date" value="2026-08-05"' in editor
    assert 'name="expected_row_version" value="2"' in editor
    assert '<select' not in editor and 'id="rate-date"' not in editor
    task.saved.assert_not_called()


def test_binding_refusal_happens_before_lookup_review_or_command(task, monkeypatch):
    retained = HTMLResponse("original retained", status_code=409)
    monkeypatch.setattr(web_budget_fx, "preserve_original_ledger_form", lambda *a, **k: retained)
    read = Mock(side_effect=AssertionError("must not look up a switched ledger"))
    monkeypatch.setattr(web_budget_fx, "list_exchange_rates", read)
    response = task.client.post("/web/budget-advise/rates", data=_form(review_latest="true"))
    assert response.status_code == 409 and response.text == "original retained"
    task.saved.assert_not_called()


def test_native_rate_command_requires_csrf_before_entering_save(task, monkeypatch):
    from app.middleware import csrf

    monkeypatch.setattr(csrf, "_csrf_secret", lambda: b"synthetic-manual-rate-test-secret")
    app = task.client.app
    app.middleware("http")(csrf.csrf_loopback_form_guard)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50100)) as client:
        refused = client.post("/web/budget-advise/rates", data=_form())
        assert refused.status_code == 403
        task.saved.assert_not_called()
        client.cookies.set(csrf.CSRF_COOKIE_NAME, "synthetic-rate-browser-seed")
        fields = _form(csrf_token=csrf._csrf_token_for_seed("synthetic-rate-browser-seed"))
        accepted = client.post("/web/budget-advise/rates", data=fields, headers={"Origin": "http://127.0.0.1"})
        assert accepted.status_code == 200, accepted.text
        task.saved.assert_called_once()
