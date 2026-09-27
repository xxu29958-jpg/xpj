"""One monthly intention survives native editing, cross-client reads and conflicts."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import LedgerMember
from app.routes.web_monthly_arrangement import MonthlyArrangementForm, arrangement_payload
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_budgets import web_client as web_client

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


@pytest.mark.parametrize("version", ["", "0", "yesterday"])
def test_missing_version_never_becomes_permission_to_create_a_new_arrangement(version):
    form = MonthlyArrangementForm(home_currency_code="JPY", savings_target_yuan="500", expected_row_version=version)
    with pytest.raises(AppError) as exc:
        arrangement_payload(form)
    assert exc.value.error == "state_conflict" and form.savings_target_yuan == "500"
