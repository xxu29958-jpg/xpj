"""Actual recognition pages retain independent intent and acknowledge only its original command."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.middleware.logging import SanitizedLoggingMiddleware
from app.models import ApiIdempotencyKey, Expense
from app.routes import web_expense_recognition
from app.services import expense_ocr_command_service as command
from tests import test_web_expense_review_runtime as review_tests
from tests._web_native_form_support import hidden_post_forms

confirmation_store = review_tests.confirmation_store
confirmation_web = review_tests.confirmation_web
review_browser = review_tests.review_browser


@pytest.fixture
def recognition_browser(review_browser, confirmation_store, monkeypatch):
    client, scope = review_browser
    options = [SimpleNamespace(ledger_id="owner", name="家庭账本", role="owner", is_default=True)]
    client.app.include_router(web_expense_recognition.router)
    monkeypatch.setattr(web_expense_recognition, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_expense_recognition, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(web_expense_recognition, "resolve_web_actor", lambda *args: (None, None))
    monkeypatch.setattr(command, "prepare_pending_expense_fx", lambda *args, **kwargs: None)
    accepted = []

    def suggest(db, expense_id, tenant_id, *, expected_row_version, **kwargs):
        current = db.get(Expense, expense_id)
        if current.status != "pending" or current.row_version != expected_row_version:
            raise AppError("state_conflict", status_code=409)
        current.merchant, current.row_version = "识别建议", current.row_version + 1
        accepted.append(expense_id)
        db.flush()
        return current

    monkeypatch.setattr(command, "retry_expense_ocr", suggest)
    monkeypatch.setattr(command, "recognize_expense_text", lambda db, expense_id, tenant_id, payload, **kwargs:
        suggest(db, expense_id, tenant_id, expected_row_version=payload.expected_row_version))
    with Session(confirmation_store) as db:
        db.get(Expense, 42).image_path = "controlled-original.png"
        db.commit()

    @client.app.get("/recognition-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/recognition_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/recognition-later-fact")
    def later_fact():
        with Session(confirmation_store) as db:
            current = db.get(Expense, 42)
            current.merchant, current.row_version = "后来人工核对", 12
            db.commit()
        return {"changed": True}

    client.app.state.expense_review_probe = "recognition-probe.js"
    return client, scope, options, accepted


def _fields(client, path):
    page = client.get(path + "?ledger_id=owner&return_to=pending&return_filter=ready")
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)[path]
    if path.endswith("recognize-text"):
        fields["raw_text"] = "便利店\n合计 JPY 2850\n原粘贴文字"
    return fields


@pytest.mark.parametrize("suffix", ["recognize-text", "ocr/retry"])
def test_recognition_acknowledges_original_request_without_overwriting_later_facts(recognition_browser, confirmation_store, suffix):
    client, scope, _, accepted = recognition_browser
    path = "/web/expenses/42/" + suffix
    fields = _fields(client, path)
    first = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert first.status_code == 200, first.text
    assert first.json()["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status, current.fact_revision) == ("识别建议", 5, "pending", 0)
    client.post("/recognition-later-fact")
    replay = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert replay.json() == first.json() and accepted == [42]
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status) == ("后来人工核对", 12, "pending")


@pytest.mark.parametrize("change", ["identity", "viewer", "version"])
def test_recognition_refuses_changed_binding_or_fact_with_original_input_retained(recognition_browser, change):
    client, scope, options, accepted = recognition_browser
    path = "/web/expenses/42/recognize-text"
    fields = _fields(client, path)
    if change == "identity":
        fields["draft_scope"] = json.dumps({**scope, "deviceId": "old-browser"})
    elif change == "viewer":
        options[0].role = "viewer"
    else:
        client.post("/recognition-later-fact")
    rejected = client.post(path, data=fields)
    assert rejected.status_code == (403 if change == "viewer" else 409), rejected.text
    retained = hidden_post_forms(rejected.text)[path]
    for name in ("idempotency_key", "expected_row_version", "draft_ref", "draft_scope", "return_filter"):
        assert retained[name] == fields[name]
    assert fields["raw_text"] in rejected.text and not accepted
    if change == "version":
        reviewed = client.post(path, data={**fields, "review_latest": "true"})
        prepared = hidden_post_forms(reviewed.text)[path]
        assert reviewed.status_code == 200 and prepared["expected_row_version"] == "12"
        assert prepared["idempotency_key"] != fields["idempotency_key"]
        assert prepared["draft_ref"] == fields["draft_ref"] and fields["raw_text"] in reviewed.text
        assert not accepted, "核对依据不能启动识别"


@pytest.mark.parametrize("kind", ["text", "image"])
def test_browser_resumes_recognition_and_original_financial_draft_after_lost_reply(recognition_browser, confirmation_store, tmp_path, kind):
    client, _, _, accepted = recognition_browser
    result = review_tests._run_review_page(client, tmp_path,
        "/web/expenses/42/edit?ledger_id=owner&return_to=pending&recognition_probe=" + kind)
    assert not result.get("error"), result
    assert result["restored"] and result["financial_retained"] and result["recognition_removed"]
    assert result["requests"][0] == result["requests"][1] and accepted == [42]
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.row_version, current.status) == ("后来人工核对", 12, "pending")


def test_recognition_keeps_unsaved_text_in_page_when_browser_cannot_retain_it(recognition_browser, tmp_path):
    client, _, _, accepted = recognition_browser
    result = review_tests._run_review_page(client, tmp_path,
        "/web/expenses/42/edit?ledger_id=owner&recognition_probe=storage")
    assert not result.get("error"), result
    assert result["leaving_prevented"] and result["retained_in_page"], result
    assert "未能保留" in result["warning"] and not accepted


@pytest.mark.parametrize("suffix", ["recognize-text", "ocr/retry"])
def test_recognition_failure_preserves_original_and_reports_through_http_owner(recognition_browser, confirmation_store, monkeypatch, caplog, suffix):
    client, _, _, _ = recognition_browser
    client.app.add_middleware(SanitizedLoggingMiddleware)
    path = "/web/expenses/42/" + suffix
    fields = _fields(client, path)
    failure = SQLAlchemyError("controlled recognition storage interruption")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(command, "prepare_pending_expense_fx", fail)
    native = client.post(path, data=fields)
    retained = hidden_post_forms(native.text)[path]
    for name in ("idempotency_key", "expected_row_version", "draft_scope", "draft_ref"):
        assert retained[name] == fields[name]
    enhanced = client.post(path, data=fields, headers={"Accept": "application/json"})
    assert enhanced.json()["draft_result"] == "blocked" and "ack" not in enhanced.json()
    for response in (native, enhanced):
        assert response.status_code == 503 and str(failure) not in response.text
        assert any(record.name == "ticketbox.http" and record.exc_info and record.exc_info[1] is failure
            and response.headers["X-Request-Id"] in record.getMessage() for record in caplog.records)
    with Session(confirmation_store) as db:
        current = db.get(Expense, 42)
        assert (current.row_version, current.merchant) == (4, "首次便利店")
        assert db.scalar(select(ApiIdempotencyKey)) is None
